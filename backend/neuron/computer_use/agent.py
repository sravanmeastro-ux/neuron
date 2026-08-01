"""Computer Use Agent — operate any Windows app via composed systems.

Pipeline: Goal → Plan (scenarios / TaskPlan) → Observe → Act → Verify → Recover
Uses Screen Understanding, Task Planning, Vision, OCR, FastIntent (indirectly
via tools) without modifying those packages.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.computer_use import act as act_mod
from neuron.computer_use import observe as obs_mod
from neuron.computer_use.detect import looks_like_computer_use
from neuron.computer_use.scenarios import actions_to_taskgraph, plan_actions
from neuron.computer_use.types import CUAction, CUReport, CUStatus


def _log(msg: str) -> None:
    print(f"[computer_use] {msg}", flush=True)


def _interrupted() -> bool:
    try:
        from neuron.speech import interrupt as interrupt_mod
        return bool(interrupt_mod.interrupted())
    except Exception:
        return False


def run_actions(
    goal: str,
    actions: list[CUAction],
    *,
    confirmed: bool = False,
    planner_ms: float = 0.0,
    source: str = "",
) -> tuple[str, bool, dict]:
    t0 = time.perf_counter()
    observations = []
    history = []
    retries = 0
    recoveries = 0
    ok_n = 0
    fail_n = 0
    status = CUStatus.RUNNING
    say_parts: list[str] = []

    i = 0
    attempts: dict[str, int] = {}
    while i < len(actions):
        if _interrupted():
            status = CUStatus.CANCELLED
            say_parts.append("Interrupted.")
            break

        action = actions[i]
        aid = action.action_id
        attempts[aid] = attempts.get(aid, 0) + 1

        if action.requires_confirm and not confirmed:
            status = CUStatus.WAITING_CONFIRM
            say = (
                f"Confirm before: {action.description}. "
                f"Say 'confirm' to proceed, or 'cancel'."
            )
            report = CUReport(
                goal=goal,
                status=status.value,
                success=False,
                steps_total=len(actions),
                steps_ok=ok_n,
                steps_failed=fail_n,
                recoveries=recoveries,
                retries=retries,
                planner_ms=planner_ms,
                execution_ms=round((time.perf_counter() - t0) * 1000, 2),
                say=say,
                path=f"computer_use:{source}",
                actions=[a.to_dict() for a in actions],
                observations=observations[-5:],
            )
            try:
                from neuron.safety import confirm as confirm_mod
                confirm_mod.request_confirm(
                    action.kind,
                    action.args,
                    action.description,
                )
            except Exception:
                pass
            return say, True, {
                "path": "computer_use",
                "needs_confirm": {
                    "action": action.kind,
                    "args": action.args,
                    "reason": action.description,
                    "goal": goal,
                    "resume_index": i,
                    "source": source,
                },
                "report": report.to_dict(),
                "pending_actions": [a.to_dict() for a in actions[i:]],
            }

        before = obs_mod.observe(use_ocr=True)
        observations.append(before.to_dict())
        _log(f"act {i+1}/{len(actions)} {action.kind}: {action.description[:60]}")

        ok, msg, meta = act_mod.execute_action(action, confirmed=confirmed)
        after = obs_mod.observe(use_ocr=True)
        observations.append(after.to_dict())
        verified = ok and act_mod.verify_action(action, before, after)

        history.append({
            "action": action.to_dict(),
            "ok": verified,
            "msg": msg,
            "meta": meta,
            "attempt": attempts[aid],
        })

        if verified:
            ok_n += 1
            if msg:
                say_parts.append(msg[:160])
            i += 1
            continue

        # Failure → recover
        retries += 1
        fail_n += 1
        alt = act_mod.recover(action, msg, attempt=attempts[aid])
        if alt is not None:
            recoveries += 1
            _log(f"recovery -> {alt.kind}")
            actions[i] = alt
            continue

        if attempts[aid] < 3:
            time.sleep(0.2)
            continue

        status = CUStatus.FAILED
        say_parts.append(f"Failed at: {action.description}. {msg}")
        break
    else:
        status = CUStatus.COMPLETED

    exec_ms = round((time.perf_counter() - t0) * 1000, 2)
    success = status == CUStatus.COMPLETED
    say = " ".join(say_parts).strip() or (
        f"Completed computer-use goal ({ok_n}/{len(actions)} steps)."
        if success
        else f"Computer-use stopped ({status.value})."
    )
    report = CUReport(
        goal=goal,
        status=status.value,
        success=success,
        steps_total=len(actions),
        steps_ok=ok_n,
        steps_failed=fail_n,
        recoveries=recoveries,
        retries=retries,
        planner_ms=planner_ms,
        execution_ms=exec_ms,
        say=say,
        path=f"computer_use:{source}",
        actions=history,
        observations=observations[-8:],
    )
    _log(
        f"done status={status.value} ok={ok_n} fail={fail_n} "
        f"retries={retries} recoveries={recoveries} ms={exec_ms}"
    )
    return say, True, {
        "path": "computer_use",
        "report": report.to_dict(),
        "recovered": recoveries > 0,
        "retries": retries,
    }


def handle(
    text: str,
    *,
    loop: Any | None = None,
    confirmed: bool = False,
    force: bool = False,
    resume_actions: list[dict] | None = None,
) -> tuple[str | None, bool, dict] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if not force and not looks_like_computer_use(raw):
        return None

    # Resume after confirm
    if resume_actions and confirmed:
        actions = [
            CUAction(
                kind=a.get("kind") or "",
                args=dict(a.get("args") or {}),
                description=str(a.get("description") or ""),
                expected=str(a.get("expected") or ""),
                requires_confirm=False,
                action_id=str(a.get("action_id") or ""),
            )
            for a in resume_actions
        ]
        return run_actions(raw, actions, confirmed=True, source="resume")

    actions, source, planner_ms = plan_actions(raw)

    # Delegate to Task Planning when templates match (Download Blender, etc.)
    if source == "taskplan_delegate":
        try:
            from neuron.taskplan.engine import handle as tp_handle
            r = tp_handle(raw, loop=loop, confirmed=confirmed, force=True)
            if r is not None:
                say, acted, meta = r
                meta = dict(meta or {})
                meta["path"] = meta.get("path") or "computer_use"
                meta["via"] = "taskplan"
                return say, acted, meta
        except Exception as exc:
            _log(f"taskplan delegate failed: {exc}")
            from neuron.computer_use.scenarios import _download_blender
            actions = _download_blender()
            source = "scenario:download_blender"
            planner_ms = 0.0

    if not actions:
        # Last resort: vision computer_use single shot
        actions = [
            CUAction(
                kind="vision",
                args={"goal": raw},
                description=raw,
                requires_confirm=True,
            )
        ]
        source = "vision_only"

    # Prefer executing via TaskGraph when possible (gets AgentLoop verify)
    graph = actions_to_taskgraph(raw, actions)
    if graph is not None and loop is not None and not any(a.kind == "vision" for a in actions[:2]):
        try:
            from neuron.taskplan.engine import run_graph
            # Strip confirm on first safe steps; keep confirm flags on graph
            say, acted, meta = run_graph(graph, loop=loop, confirmed=confirmed)
            meta = dict(meta or {})
            meta["via"] = "taskplan_graph"
            meta["path"] = "computer_use"
            meta["cu_source"] = source
            meta["planner_ms"] = planner_ms
            return say, acted, meta
        except Exception as exc:
            _log(f"taskgraph path failed: {exc}")

    return run_actions(raw, actions, confirmed=confirmed, planner_ms=planner_ms, source=source)


def tool_computer_use_agent(args: dict | None = None) -> Any:
    args = args or {}
    text = (args.get("goal") or args.get("request") or args.get("query") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    from neuron.windows.result import ok, fail
    r = handle(text, confirmed=confirmed, force=True)
    if r is None:
        return fail("Not a computer-use goal.")
    say, acted, meta = r
    if meta.get("report", {}).get("success") or acted:
        return ok(say or "OK", state=meta, method="computer_use_agent")
    return fail(say or "Computer use failed.", state=meta, method="computer_use_agent")
