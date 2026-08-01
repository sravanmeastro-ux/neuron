"""Autonomous execution engine — upgrades Task Planner with full OPAVR loop."""

from __future__ import annotations

import time
from typing import Any

from neuron.autonomous import correct, progress, replan, risk, verify
from neuron.taskplan import observe as obs_mod
from neuron.taskplan import state as state_mod
from neuron.taskplan.decompose import build_graph
from neuron.taskplan.extract import extract_goal
from neuron.taskplan.types import (
    ExecutionReport,
    StepStatus,
    TaskGraph,
    TaskState,
    TaskStatus,
)


def _cfg_enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
        agent = cfg.get("agent") or {}
        if agent.get("autonomous_execution") is False:
            return False
        return bool(agent.get("task_planning_engine", True))
    except Exception:
        return True


def _log(msg: str) -> None:
    print(f"[autonomous] {msg}", flush=True)


def _interrupted() -> bool:
    try:
        from neuron.speech import interrupt as interrupt_mod
        return bool(interrupt_mod.interrupted())
    except Exception:
        return False


def plan_goal(text: str) -> tuple[Any, TaskGraph | None, dict[str, Any]]:
    """Goal planning + task decomposition + risk assessment."""
    goal = extract_goal(text)
    graph = build_graph(text, goal=goal)
    risk_info: dict[str, Any] = {}
    if graph:
        risk_info = risk.assess_plan(graph)
        graph.goal = goal
    return goal, graph, risk_info


def _build_report(state: TaskState, *, extra: dict | None = None) -> ExecutionReport:
    g = state.graph
    steps = list(g.subtasks) if g else []
    completed = sum(1 for s in steps if s.status == StepStatus.COMPLETED)
    failed = sum(1 for s in steps if s.status == StepStatus.FAILED)
    total_ms = round((time.time() - state.started_at) * 1000, 2) if state.started_at else 0.0
    rep = ExecutionReport(
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
    if extra:
        # Attach autonomous extras onto say/meta via dict later
        d = rep.to_dict()
        d.update(extra)
        # stash on instance for callers using to_dict only — return via meta
        rep._autonomous_extra = extra  # type: ignore[attr-defined]
    return rep


def run_autonomous(
    graph: TaskGraph,
    *,
    loop: Any | None = None,
    confirmed: bool = False,
    resume_state: TaskState | None = None,
    risk_info: dict[str, Any] | None = None,
) -> tuple[str, bool, dict]:
    """
    Fully autonomous execution:
    Goal plan → decompose (done) → execute → verify → self-correct → recover →
    dynamic replan → progress track → confirm destructive → goal verify.
    """
    from neuron.taskplan.engine import _execute_subtask

    t0 = time.perf_counter()
    risk_info = risk_info or risk.assess_plan(graph)
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

    corrections = 0
    dynamic_replans = 0
    verifications: list[dict] = []
    goal_verify: dict[str, Any] = {}

    done_set = set(state.completed_ids or [])
    for s in graph.subtasks:
        if s.subtask_id in done_set:
            s.status = StepStatus.COMPLETED

    _log(
        f"start plan={graph.plan_id} steps={len(graph.subtasks)} "
        f"risk={risk_info.get('level')} confirm_n={risk_info.get('confirm_required_count')}"
    )

    while True:
        if _interrupted() or state.status == TaskStatus.CANCELLED:
            state.status = TaskStatus.CANCELLED
            state.say = "Interrupted — autonomous task cancelled."
            break

        if graph.all_done():
            # Goal-level verification
            state.sync_from_graph()
            goal_verify = verify.verify_goal(
                state.goal,
                steps_completed=len(state.completed_ids),
                steps_total=len(graph.subtasks),
                observations=state.recent_observations,
                success_flag=True,
            )
            if goal_verify.get("passed"):
                state.status = TaskStatus.COMPLETED
                state.say = (
                    f"Done. Completed {len(state.completed_ids)}/{len(graph.subtasks)} steps "
                    f"for: {graph.goal.summary or graph.goal.text[:80]}."
                )
                break
            # Self-correct: dynamic replan remaining criteria miss
            rp = replan.replan_remaining(graph, goal_text=graph.goal.text)
            if rp.get("replanned"):
                dynamic_replans += 1
                _log(f"goal verify miss → dynamic replan {rp}")
                continue
            state.status = TaskStatus.COMPLETED  # soft complete with note
            state.say = (
                f"Finished with soft goal check. "
                f"Hits={goal_verify.get('criteria_hit')} misses={goal_verify.get('criteria_miss')}."
            )
            break

        if graph.has_failed_terminal():
            rp = replan.replan_remaining(graph, goal_text=graph.goal.text)
            if rp.get("replanned") and not graph.has_failed_terminal():
                dynamic_replans += 1
                continue
            # Try one more recovery pass on failed nodes
            recovered_any = False
            for s in list(graph.subtasks):
                if s.status == StepStatus.FAILED and s.attempt_count < s.max_attempts + 1:
                    alts = correct.suggest_corrections(s, s.last_error)
                    if alts and replan.apply_correction(s, alts[0]):
                        s.status = StepStatus.PENDING
                        s.attempt_count = max(0, s.attempt_count - 1)
                        corrections += 1
                        recovered_any = True
                        state.recovery_count += 1
            if recovered_any:
                continue
            state.status = TaskStatus.FAILED
            state.say = f"Stopped after failures. {state.last_error}"
            break

        ready = graph.ready()
        if not ready:
            rp = replan.replan_remaining(graph, goal_text=graph.goal.text)
            if rp.get("replanned"):
                dynamic_replans += 1
                ready = graph.ready()
            if not ready:
                state.status = TaskStatus.FAILED
                state.say = "No runnable steps left (dependency deadlock or all blocked)."
                break

        sub = ready[0]
        state.current_subtask_id = sub.subtask_id

        before = obs_mod.observe()
        state_mod.remember_observation(before)
        state.current_application = before.application or state.current_application
        state.focused_window = before.window_title or state.focused_window

        need, reason = risk.must_confirm(sub, confirmed=confirmed)
        if need:
            state.status = TaskStatus.WAITING_CONFIRM
            state.pending_confirm = {
                "action": sub.action,
                "args": dict(sub.args or {}),
                "reason": reason,
                "subtask_id": sub.subtask_id,
                "description": sub.description,
                "risk": risk.assess_action(sub.action, sub.args),
            }
            state.say = (
                f"Confirm before destructive/sensitive step: {sub.description}. "
                f"Say 'confirm' to proceed, or 'cancel' to stop."
            )
            state.execution_ms = round((time.perf_counter() - t0) * 1000, 2)
            state.sync_from_graph()
            state_mod.set_state(state)
            try:
                from neuron.safety import confirm as confirm_mod
                confirm_mod.request_confirm(sub.action, sub.args or {}, reason)
            except Exception:
                pass
            report = _build_report(state)
            return state.say, True, {
                "path": "autonomous",
                "needs_confirm": state.pending_confirm,
                "report": report.to_dict(),
                "task_state": state.to_dict(),
                "progress": progress.snapshot(state),
                "risk": risk_info,
            }

        sub.status = StepStatus.RUNNING
        sub.attempt_count += 1
        _log(f"step {sub.action} attempt={sub.attempt_count}")

        ok, msg, meta = _execute_subtask(sub, confirmed=confirmed, loop=loop)

        if meta.get("interrupted"):
            state.status = TaskStatus.CANCELLED
            state.say = msg or "Interrupted."
            break

        if meta.get("needs_confirm"):
            state.status = TaskStatus.WAITING_CONFIRM
            state.pending_confirm = meta["needs_confirm"]
            state.say = msg or "Confirmation required. Say 'confirm' to proceed."
            state.execution_ms = round((time.perf_counter() - t0) * 1000, 2)
            state.sync_from_graph()
            state_mod.set_state(state)
            report = _build_report(state)
            return state.say, True, {
                "path": "autonomous",
                "needs_confirm": state.pending_confirm,
                "report": report.to_dict(),
                "progress": progress.snapshot(state),
                "risk": risk_info,
            }

        after = obs_mod.observe()
        state_mod.remember_observation(after)
        v = verify.verify_step(sub, before=before, after=after, ok_flag=ok, message=msg)
        verifications.append(v)

        if ok and v.get("passed"):
            sub.status = StepStatus.COMPLETED
            sub.last_error = ""
            if sub.subtask_id not in state.completed_ids:
                state.completed_ids.append(sub.subtask_id)
            continue

        # Failure / soft verify fail → self-correction + recovery
        state.retry_count += 1
        state.last_error = msg or "verification failed"
        sig = sub.signature()
        if sig == sub.last_signature and sub.attempt_count >= 2:
            _log(f"identical failure — skip {sub.action}")
            sub.status = StepStatus.FAILED
            state.failed_ids.append(sub.subtask_id)
            # Dynamic replan after hard fail
            rp = replan.replan_remaining(graph, goal_text=graph.goal.text)
            if rp.get("replanned"):
                dynamic_replans += 1
            continue

        sub.last_signature = sig
        sub.last_error = state.last_error
        alts = correct.suggest_corrections(sub, state.last_error)

        if alts and sub.attempt_count < sub.max_attempts:
            # Prefer in-place correction; optionally insert recovery node once
            alt = alts[0]
            if sub.attempt_count == 1 and alt.get("reason") in ("screen_fallback", "refocus"):
                inserted = replan.insert_recovery_subtask(graph, sub, alt)
                if inserted:
                    state.recovery_count += 1
                    corrections += 1
                    dynamic_replans += 1
                    sub.status = StepStatus.PENDING
                    _log(f"inserted recovery {inserted.action}")
                    continue
            if replan.apply_correction(sub, alt):
                state.recovery_count += 1
                corrections += 1
                sub.status = StepStatus.PENDING
                _log(f"self-correct -> {sub.action} ({alt.get('reason')})")
                continue

        if sub.attempt_count < sub.max_attempts:
            sub.status = StepStatus.PENDING
            time.sleep(0.12)
            continue

        sub.status = StepStatus.FAILED
        state.failed_ids.append(sub.subtask_id)

    state.execution_ms = round((time.perf_counter() - t0) * 1000, 2)
    state.sync_from_graph()
    if not goal_verify and state.status == TaskStatus.COMPLETED:
        goal_verify = verify.verify_goal(
            state.goal,
            steps_completed=len(state.completed_ids),
            steps_total=len(graph.subtasks),
            observations=state.recent_observations,
            success_flag=True,
        )
    state_mod.set_state(state)
    report = _build_report(state)
    rd = report.to_dict()
    rd["risk"] = risk_info
    rd["corrections"] = corrections
    rd["dynamic_replans"] = dynamic_replans
    rd["verifications"] = verifications[-8:]
    rd["goal_verify"] = goal_verify
    rd["progress"] = progress.snapshot(state)

    if state.status == TaskStatus.COMPLETED:
        state_mod.clear_state()

    _log(
        f"done status={state.status.value} corrections={corrections} "
        f"replans={dynamic_replans} exec_ms={state.execution_ms}"
    )
    return state.say, True, {
        "path": "autonomous",
        "report": rd,
        "task_state": state.to_dict() if state.status != TaskStatus.COMPLETED else None,
        "recovered": state.recovery_count > 0,
        "retries": state.retry_count,
        "progress": progress.snapshot(state) if state.status != TaskStatus.COMPLETED else rd.get("progress"),
        "risk": risk_info,
        "corrections": corrections,
        "dynamic_replans": dynamic_replans,
    }


def handle_autonomous(
    text: str,
    *,
    loop: Any | None = None,
    confirmed: bool = False,
    force: bool = False,
) -> tuple[str | None, bool, dict] | None:
    """Entry used by upgraded taskplan handle when autonomous mode is on."""
    from neuron.taskplan.detect import (
        is_cancel_command,
        is_confirm_command,
        is_resume_command,
        looks_like_workflow,
    )
    from neuron.taskplan.engine import cancel_active

    raw = (text or "").strip()
    if not raw:
        return None
    if is_cancel_command(raw):
        return cancel_active()

    st = state_mod.get_state()
    if st is None:
        state_mod.load_persisted()
        st = state_mod.get_state()

    if is_confirm_command(raw) and st and st.status == TaskStatus.WAITING_CONFIRM and st.graph:
        return run_autonomous(st.graph, loop=loop, confirmed=True, resume_state=st)

    if is_resume_command(raw):
        if st and st.graph and st.status in (
            TaskStatus.PAUSED,
            TaskStatus.WAITING_CONFIRM,
            TaskStatus.FAILED,
            TaskStatus.RUNNING,
        ):
            return run_autonomous(st.graph, loop=loop, confirmed=confirmed, resume_state=st)
        return "No paused task to resume.", True, {"path": "autonomous"}

    if not force and not looks_like_workflow(raw):
        return None

    goal, graph, risk_info = plan_goal(raw)
    if graph is None or not graph.subtasks:
        return None
    _log(
        f"planned source={graph.source} steps={len(graph.subtasks)} "
        f"risk={risk_info.get('level')} destructive={goal.destructive}"
    )
    return run_autonomous(graph, loop=loop, confirmed=confirmed, risk_info=risk_info)


def tool_autonomous_run(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    text = (args.get("request") or args.get("goal") or args.get("query") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    result = handle_autonomous(text, confirmed=confirmed, force=True)
    if result is None:
        return fail("Not a multi-step goal.")
    say, acted, meta = result
    if meta.get("report", {}).get("success") or acted:
        return ok(say or "OK", state=meta, method="autonomous")
    return fail(say or "Failed.", state=meta, method="autonomous")


def tool_autonomous_progress(args: dict | None = None) -> Any:
    from neuron.windows.result import ok
    st = state_mod.get_state()
    if st is None:
        state_mod.load_persisted()
        st = state_mod.get_state()
    snap = progress.snapshot(st)
    steps = progress.step_table(st)
    return ok(
        f"Progress {snap.get('progress_pct')}% ({snap.get('status')})",
        state={"progress": snap, "steps": steps},
        method="autonomous",
    )


def tool_autonomous_assess(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    text = (args.get("request") or args.get("goal") or "").strip()
    if not text:
        return fail("Need goal text.")
    goal, graph, risk_info = plan_goal(text)
    if not graph:
        return fail("Could not build a plan.")
    return ok(
        f"Plan ready: {len(graph.subtasks)} steps, risk={risk_info.get('level')}",
        state={
            "goal": goal.to_dict(),
            "plan": graph.to_dict(),
            "risk": risk_info,
            "progress": {"progress_pct": 0, "steps_total": len(graph.subtasks)},
        },
        method="autonomous",
    )
