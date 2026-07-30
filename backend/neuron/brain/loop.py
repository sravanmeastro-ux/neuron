"""Phase 9 — Observe → Plan → Act → Verify → Recover loop.

NEURON never assumes success. After every meaningful step:
  observe result → verify → success or recover from current state.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.brain import executor
from neuron.brain import planner
from neuron.brain import recover
from neuron.brain import verifier
from neuron.brain.goal import GoalState
from neuron.brain.normalize import normalize_plan
from neuron.brain.trace import Trace


def _cfg() -> dict:
    try:
        import json
        from pathlib import Path
        return json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(
                encoding="utf-8"
            )
        ).get("agent") or {}
    except Exception:
        return {}


def run_opavr(
    *,
    request: str,
    context: str = "",
    normalized: str = "",
    plan: dict | None = None,
    confirmed: bool = False,
    observe_blob: str = "",
    trace: Trace | None = None,
) -> tuple[str | None, bool, dict[str, Any], GoalState]:
    """
    Execute a plan under OPAVR.

    If plan is None, plans from request+context first.
    Returns (say, acted, meta, goal_state).
    """
    cfg = _cfg()
    max_retries = int(cfg.get("max_replans", 3) or 3)
    max_step_retries = int(cfg.get("max_step_retries", 2) or 2)
    max_iters = int(cfg.get("max_loop_iterations", 12) or 12)
    strict = bool(cfg.get("strict_verify", True))

    tr = trace or Trace()
    meta: dict[str, Any] = {
        "path": "opavr",
        "replanned": False,
        "recovered": False,
        "steps": [],
        "needs_confirm": None,
    }

    goal_text = (normalized or request or "").strip()
    tr.user(request)
    if observe_blob or context:
        tr.context(observe_blob or context[:800])

    # PLAN
    if plan is None:
        plan = planner.plan(request, context, normalized=normalized)
    if plan is None:
        meta["path"] = "plan_failed"
        tr.final("failed", "Planner unavailable")
        g = GoalState(goal=goal_text, status="failed", max_retries=max_retries)
        g.mark_failed("Planner returned no plan")
        return None, False, meta, g

    plan = normalize_plan(plan)
    goal = GoalState.from_plan(goal_text, plan, max_retries=max_retries)
    tr.plan(plan)

    # Pure chat — no tools
    if not goal.pending_steps:
        say = (plan.get("say") or "").strip()
        goal.mark_success()
        tr.final("success", say or "")
        meta["steps"] = []
        return say or None, bool(say), meta, goal

    step_retries = 0
    iterations = 0

    while goal.pending_steps and iterations < max_iters:
        iterations += 1
        step = dict(goal.pending_steps[0])

        # OBSERVE (before act)
        world_before = verifier.observe_world(
            str((step.get("args") or {}).get("name") or goal.goal)
        )
        goal.update_observation(world_before, note="pre-act")

        # ACT
        tr.action(step)
        er = executor.execute_plan({"say": "", "steps": [step]}, confirmed=confirmed)
        meta["steps"] = list(goal.action_history)  # updated below

        if er.needs_confirm:
            goal.status = "needs_confirm"
            meta["needs_confirm"] = er.needs_confirm
            tr.result(False, er.needs_confirm.get("reason") or "confirm required")
            tr.final("needs_confirm", "Confirmation required")
            return None, True, meta, goal

        entry = er.steps_run[-1] if er.steps_run else {
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": False,
            "out": (er.errors[-1] if er.errors else "no result"),
        }
        act_ok = bool(entry.get("ok")) and not er.errors
        tr.result(act_ok, entry.get("out") or "", ms=entry.get("ms"))

        # OBSERVE RESULT + VERIFY
        world_after = verifier.observe_world(
            str((step.get("args") or {}).get("name") or goal.goal)
        )
        goal.update_observation(world_after, note="post-act")
        vr = verifier.verify_execution_step(step, entry, strict=strict)
        tr.verification(vr.ok, vr.note, **(vr.evidence or {}))

        if vr.ok and act_ok:
            goal.complete_current(step, entry, verify_note=vr.note)
            step_retries = 0
            meta["steps"] = list(goal.action_history)
            continue

        # Failure — do not claim success
        err = vr.note or (er.errors[-1] if er.errors else "verification failed")
        goal.fail_current(step, err, entry)

        # RECOVER from current state (not full restart)
        if step_retries >= max_step_retries or not goal.bump_retry():
            goal.mark_failed(err)
            say = goal.honest_failure_message()
            tr.final("failed", say)
            meta["steps"] = list(goal.action_history)
            return say, True, meta, goal

        step_retries += 1
        remaining = list(goal.pending_steps[1:])  # skip failed head

        # 1) Deterministic alternate method (one at a time)
        alt = recover.deterministic_recovery(step, err, goal)
        if alt:
            new_pending = recover.merge_recovery(step, remaining, [alt[0]])
            goal.set_pending(new_pending)
            meta["recovered"] = True
            tr.replan(f"deterministic recover: {err}", new_pending)
            continue

        # 2) LLM replan — remaining work only
        meta["replanned"] = True
        retry_plan = recover.llm_replan_pending(
            request,
            context,
            goal,
            step,
            err,
            normalized=normalized,
        )
        if not retry_plan or not (retry_plan.get("steps") or []):
            # Planner gave up — explain honestly
            say = (retry_plan or {}).get("say") if retry_plan else None
            say = (say or "").strip() or goal.honest_failure_message()
            goal.mark_failed(err)
            tr.replan(f"no recovery plan: {err}", [])
            tr.final("failed", say)
            meta["steps"] = list(goal.action_history)
            return say, True, meta, goal

        new_steps = normalize_plan(retry_plan).get("steps") or []
        # Keep remaining only from replan (already should be pending-only)
        goal.set_pending(new_steps)
        if retry_plan.get("say"):
            goal.plan_say = str(retry_plan.get("say") or "")
        tr.replan(err, new_steps)

    if goal.pending_steps:
        goal.mark_failed("Retry/iteration limit reached")
        say = goal.honest_failure_message()
        tr.final("failed", say)
        meta["steps"] = list(goal.action_history)
        return say, True, meta, goal

    goal.mark_success()
    # Prefer last verified outcome over optimistic plan.say
    say = ""
    if goal.action_history:
        last = goal.action_history[-1]
        if last.get("ok") and last.get("out"):
            say = str(last["out"])
    say = say or goal.plan_say or "Done."
    # If any errors occurred mid-way but we recovered, be honest if final empty
    tr.final("success", say, completed=len(goal.completed_steps))
    meta["steps"] = list(goal.action_history)
    return say, True, meta, goal
