"""Task Planning Execution Engine.

Pipeline: Goal → Plan → Subtasks → Dependency graph → Execute → Observe →
Verify → Continue (with intelligent retry / recovery / cancel / confirm).

Composes FastIntentRouter, Screen Understanding, AgentLoop, and ToolRegistry
without modifying those modules.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.taskplan import observe as obs_mod
from neuron.taskplan import state as state_mod
from neuron.taskplan.decompose import build_graph
from neuron.taskplan.detect import (
    is_cancel_command,
    is_confirm_command,
    is_resume_command,
    looks_like_workflow,
)
from neuron.taskplan.extract import extract_goal
from neuron.taskplan.types import (
    ExecutionReport,
    StepStatus,
    Subtask,
    TaskGraph,
    TaskState,
    TaskStatus,
)


def _log(msg: str) -> None:
    print(f"[taskplan] {msg}", flush=True)


def _interrupted() -> bool:
    try:
        from neuron.speech import interrupt as interrupt_mod
        return bool(interrupt_mod.interrupted())
    except Exception:
        return False


def _tool_ok(result: Any) -> bool:
    if result is None:
        return False
    if hasattr(result, "success"):
        return bool(result.success)
    if isinstance(result, dict):
        if "success" in result:
            return bool(result.get("success"))
        if result.get("ok") is False:
            return False
    s = str(result).lower()
    if any(x in s for x in ("couldn't", "could not", "failed", "error:", "unknown tool")):
        return False
    return True


def _tool_msg(result: Any) -> str:
    if result is None:
        return ""
    if hasattr(result, "message"):
        return str(result.message or "")
    if isinstance(result, dict):
        return str(result.get("message") or result.get("say") or result)
    return str(result)


def _needs_confirm(sub: Subtask, *, confirmed: bool) -> tuple[bool, str]:
    if confirmed:
        return False, ""
    if sub.requires_confirm:
        return True, f"{sub.action}: {sub.description}"
    try:
        from neuron.safety import policy
        ok, reason = policy.allow(sub.action, sub.args or {}, confirmed=False)
        if not ok:
            return True, reason or f"{sub.action} needs confirmation"
    except Exception:
        pass
    return False, ""


def _recover_steps(sub: Subtask, error: str) -> list[dict] | None:
    """Use existing recover.deterministic_recovery — never endless identical retry."""
    try:
        from neuron.brain.goal import GoalState
        from neuron.brain import recover as recover_mod
        goal = GoalState(goal=sub.description)
        goal.action_history.append({
            "action": sub.action,
            "args": dict(sub.args or {}),
            "ok": False,
            "out": error,
        })
        alts = recover_mod.deterministic_recovery(
            {"action": sub.action, "args": dict(sub.args or {})},
            error,
            goal,
        )
        return alts
    except Exception:
        return None


def _execute_subtask(sub: Subtask, *, confirmed: bool, loop: Any | None) -> tuple[bool, str, dict]:
    """
    Run one subtask via Screen / FastIntent-style tool / AgentLoop / registry.
    Returns (ok, message, meta).
    """
    meta: dict[str, Any] = {"action": sub.action, "path": "registry"}

    # Screen Understanding path
    if sub.use_screen or sub.action == "screen_understand":
        try:
            from neuron.screen import handle as screen_handle
            req = str((sub.args or {}).get("request") or sub.description)
            sr = screen_handle(req, force=True)
            if sr is not None:
                meta["path"] = "screen"
                return bool(sr.ok and sr.acted), sr.say or "", meta
        except Exception as exc:
            meta["screen_error"] = str(exc)

    # Prefer single-step AgentLoop when available (verify/recover for free)
    if loop is not None and sub.action not in ("task_move_files", "task_zip_folder"):
        try:
            plan = {
                "say": sub.description,
                "steps": [sub.as_tool_step()],
                "source": "taskplan_step",
            }
            say, acted, loop_meta, goal = loop.run(
                request=sub.description,
                normalized=sub.description,
                plan=plan,
                confirmed=confirmed,
            )
            meta["path"] = "agent_loop"
            meta["loop"] = {
                "recovered": loop_meta.get("recovered"),
                "needs_confirm": loop_meta.get("needs_confirm"),
            }
            if loop_meta.get("needs_confirm"):
                return False, say or "Confirmation required.", {**meta, "needs_confirm": loop_meta["needs_confirm"]}
            status = getattr(goal, "status", "") if goal else ""
            ok = bool(acted) and status not in ("failed", "interrupted")
            if status == "interrupted":
                return False, say or "Interrupted.", {**meta, "interrupted": True}
            return ok, say or _tool_msg(say), meta
        except Exception as exc:
            meta["loop_error"] = str(exc)

    # Direct ToolRegistry
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        result = tool_registry.execute(sub.action, sub.args or {}, confirmed=confirmed)
        ok = _tool_ok(result)
        # Policy confirm payload
        if hasattr(result, "needs_confirm") or (
            isinstance(result, dict) and result.get("needs_confirm")
        ):
            nc = getattr(result, "needs_confirm", None) or result.get("needs_confirm")
            return False, _tool_msg(result), {**meta, "needs_confirm": nc}
        msg = _tool_msg(result)
        if not ok and "confirm" in msg.lower():
            return False, msg, {
                **meta,
                "needs_confirm": {"action": sub.action, "args": sub.args, "reason": msg},
            }
        return ok, msg, meta
    except Exception as exc:
        return False, str(exc), meta


def _build_report(state: TaskState) -> ExecutionReport:
    g = state.graph
    steps = list(g.subtasks) if g else []
    completed = sum(1 for s in steps if s.status == StepStatus.COMPLETED)
    failed = sum(1 for s in steps if s.status == StepStatus.FAILED)
    total_ms = 0.0
    if state.started_at:
        total_ms = round((time.time() - state.started_at) * 1000, 2)
    return ExecutionReport(
        goal=state.goal.text,
        status=state.status.value,
        completion_ms=total_ms,
        planner_ms=state.planner_ms,
        execution_ms=state.execution_ms,
        success=state.status == TaskStatus.COMPLETED,
        steps_total=len(steps),
        steps_completed=completed,
        steps_failed=failed,
        retry_count=state.retry_count,
        recovery_count=state.recovery_count,
        cancelled=state.status == TaskStatus.CANCELLED,
        needs_confirm=state.pending_confirm,
        say=state.say,
        subtasks=[s.to_dict() for s in steps],
        observations=[o.to_dict() for o in state.recent_observations[-5:]],
    )


def cancel_active(*, say: str = "Cancelled the current task.") -> tuple[str, bool, dict]:
    st = state_mod.get_state()
    if st is None:
        return "No active task to cancel.", True, {"path": "taskplan", "cancelled": False}
    st.status = TaskStatus.CANCELLED
    st.say = say
    state_mod.set_state(st)
    report = _build_report(st)
    state_mod.clear_state()
    _log("cancelled")
    return say, True, {"path": "taskplan", "cancelled": True, "report": report.to_dict()}


def run_graph(
    graph: TaskGraph,
    *,
    loop: Any | None = None,
    confirmed: bool = False,
    resume_state: TaskState | None = None,
) -> tuple[str, bool, dict]:
    """Execute a TaskGraph until complete, blocked on confirm, failed, or cancelled."""
    t_exec0 = time.perf_counter()
    state = resume_state or TaskState(
        goal=graph.goal,
        graph=graph,
        status=TaskStatus.RUNNING,
        planner_ms=graph.planner_ms,
        started_at=time.time(),
    )
    state.graph = graph
    state.status = TaskStatus.RUNNING
    state_mod.set_state(state)

    # Mark already-completed from resume
    done_set = set(state.completed_ids or [])
    for s in graph.subtasks:
        if s.subtask_id in done_set:
            s.status = StepStatus.COMPLETED

    while True:
        if _interrupted() or (state.status == TaskStatus.CANCELLED):
            state.status = TaskStatus.CANCELLED
            state.say = "Interrupted — task cancelled."
            state.execution_ms = round((time.perf_counter() - t_exec0) * 1000, 2)
            state.sync_from_graph()
            report = _build_report(state)
            state_mod.set_state(state)
            return state.say, True, {"path": "taskplan", "report": report.to_dict(), "interrupted": True}

        if graph.all_done():
            state.status = TaskStatus.COMPLETED
            state.say = (
                f"Done. Completed {len(state.completed_ids)} steps"
                f" for: {graph.goal.summary or graph.goal.text[:80]}."
            )
            break

        if graph.has_failed_terminal():
            state.status = TaskStatus.FAILED
            state.say = f"Stopped after failures. {state.last_error}"
            break

        ready = graph.ready()
        if not ready:
            state.status = TaskStatus.FAILED
            state.say = "No runnable steps left (dependency deadlock or all blocked)."
            break

        # Execute one ready subtask (sequential for predictability)
        sub = ready[0]
        state.current_subtask_id = sub.subtask_id

        # Observe before act
        observation = obs_mod.observe()
        state_mod.remember_observation(observation)
        state.current_application = observation.application or state.current_application
        state.focused_window = observation.window_title or state.focused_window

        need, reason = _needs_confirm(sub, confirmed=confirmed)
        if need:
            state.status = TaskStatus.WAITING_CONFIRM
            state.pending_confirm = {
                "action": sub.action,
                "args": dict(sub.args or {}),
                "reason": reason,
                "subtask_id": sub.subtask_id,
                "description": sub.description,
            }
            state.say = (
                f"Confirm before: {sub.description}. "
                f"Say 'confirm' to proceed, or 'cancel' to stop."
            )
            state.execution_ms = round((time.perf_counter() - t_exec0) * 1000, 2)
            state.sync_from_graph()
            state_mod.set_state(state)
            try:
                from neuron.safety import confirm as confirm_mod
                confirm_mod.request_confirm(sub.action, sub.args or {}, reason)
            except Exception:
                pass
            report = _build_report(state)
            return state.say, True, {
                "path": "taskplan",
                "needs_confirm": state.pending_confirm,
                "report": report.to_dict(),
                "task_state": state.to_dict(),
            }

        sub.status = StepStatus.RUNNING
        sub.attempt_count += 1
        _log(f"step {sub.subtask_id} {sub.action} attempt={sub.attempt_count}")

        ok, msg, meta = _execute_subtask(sub, confirmed=confirmed, loop=loop)

        if meta.get("interrupted"):
            state.status = TaskStatus.CANCELLED
            state.say = msg or "Interrupted."
            break

        if meta.get("needs_confirm"):
            state.status = TaskStatus.WAITING_CONFIRM
            state.pending_confirm = meta["needs_confirm"]
            state.say = msg or "Confirmation required. Say 'confirm' to proceed."
            state.execution_ms = round((time.perf_counter() - t_exec0) * 1000, 2)
            state.sync_from_graph()
            state_mod.set_state(state)
            report = _build_report(state)
            return state.say, True, {
                "path": "taskplan",
                "needs_confirm": state.pending_confirm,
                "report": report.to_dict(),
            }

        if ok:
            sub.status = StepStatus.COMPLETED
            sub.last_error = ""
            state.completed_ids.append(sub.subtask_id)
            # Post-observe
            observation = obs_mod.observe()
            state_mod.remember_observation(observation)
            continue

        # Failure → intelligent recovery (alternate steps), avoid identical endless retry
        state.retry_count += 1
        state.last_error = msg
        sig = sub.signature()
        if sig == sub.last_signature and sub.attempt_count >= 2:
            _log(f"skip identical retry for {sub.action}")
            sub.status = StepStatus.FAILED
            state.failed_ids.append(sub.subtask_id)
            continue
        sub.last_signature = sig
        sub.last_error = msg

        alts = _recover_steps(sub, msg)
        if alts and sub.attempt_count < sub.max_attempts:
            alt = alts[0]
            new_sig = f"{alt.get('action')}|{sorted((alt.get('args') or {}).items())}"
            if new_sig != sig:
                state.recovery_count += 1
                sub.action = str(alt.get("action") or sub.action)
                sub.args = dict(alt.get("args") or sub.args)
                sub.status = StepStatus.PENDING
                _log(f"recovery -> {sub.action}")
                continue

        if sub.attempt_count < sub.max_attempts:
            sub.status = StepStatus.PENDING  # retry with observe again
            time.sleep(0.15)
            continue

        sub.status = StepStatus.FAILED
        state.failed_ids.append(sub.subtask_id)

    state.execution_ms = round((time.perf_counter() - t_exec0) * 1000, 2)
    state.sync_from_graph()
    state_mod.set_state(state)
    report = _build_report(state)
    if state.status == TaskStatus.COMPLETED:
        state_mod.clear_state()
    _log(
        f"done status={state.status.value} "
        f"retries={state.retry_count} recoveries={state.recovery_count} "
        f"exec_ms={state.execution_ms}"
    )
    return state.say, True, {
        "path": "taskplan",
        "report": report.to_dict(),
        "task_state": state.to_dict() if state.status != TaskStatus.COMPLETED else None,
        "recovered": state.recovery_count > 0,
        "retries": state.retry_count,
    }


def handle(
    text: str,
    *,
    loop: Any | None = None,
    confirmed: bool = False,
    force: bool = False,
) -> tuple[str | None, bool, dict] | None:
    """
    Entry for AgentLoop bridge.
    Returns None if not a workflow (caller continues normal routing).

    When autonomous_execution is enabled (default), delegates to the
    Autonomous Agent engine (goal verify, dynamic replan, risk, etc.).
    """
    # Prefer fully autonomous execution engine
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
        auto_on = (cfg.get("agent") or {}).get("autonomous_execution", True)
    except Exception:
        auto_on = True
    if auto_on:
        try:
            from neuron.autonomous.engine import handle_autonomous
            return handle_autonomous(text, loop=loop, confirmed=confirmed, force=force)
        except Exception as exc:
            _log(f"autonomous fallback to classic: {exc}")

    raw = (text or "").strip()
    if not raw:
        return None

    if is_cancel_command(raw):
        return cancel_active()

    st = state_mod.get_state()
    if st is None:
        state_mod.load_persisted()
        st = state_mod.get_state()

    # Confirm pending destructive / confirm step
    if is_confirm_command(raw) and st and st.status == TaskStatus.WAITING_CONFIRM:
        return run_graph(st.graph, loop=loop, confirmed=True, resume_state=st)  # type: ignore[arg-type]

    # Resume paused / interrupted unfinished graph
    if is_resume_command(raw):
        if st and st.graph and st.status in (
            TaskStatus.PAUSED,
            TaskStatus.WAITING_CONFIRM,
            TaskStatus.FAILED,
            TaskStatus.RUNNING,
        ):
            return run_graph(st.graph, loop=loop, confirmed=confirmed, resume_state=st)
        if st and st.goal.text:
            graph = build_graph(st.goal.text)
            if graph:
                # Skip completed
                return run_graph(graph, loop=loop, confirmed=confirmed, resume_state=st)
        return "No paused task to resume.", True, {"path": "taskplan"}

    if not force and not looks_like_workflow(raw):
        return None

    goal = extract_goal(raw)
    graph = build_graph(raw, goal=goal)
    if graph is None or not graph.subtasks:
        return None

    _log(
        f"plan source={graph.source} steps={len(graph.subtasks)} "
        f"planner_ms={graph.planner_ms} destructive={goal.destructive}"
    )
    return run_graph(graph, loop=loop, confirmed=confirmed)


def tool_run_task_workflow(args: dict | None = None) -> Any:
    """ToolRegistry handler."""
    args = args or {}
    text = (args.get("request") or args.get("goal") or args.get("query") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    from neuron.windows.result import ok, fail
    result = handle(text, confirmed=confirmed, force=True)
    if result is None:
        return fail("Not a multi-step workflow.")
    say, acted, meta = result
    if meta.get("report", {}).get("success") or acted:
        return ok(say or "OK", state=meta, method="taskplan")
    return fail(say or "Task failed.", state=meta, method="taskplan")
