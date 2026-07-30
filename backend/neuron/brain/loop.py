"""Phase 9 — Observe → Plan → Act → Verify → Recover loop.

NEURON never assumes success. After every meaningful step:
  observe → act ONE step → observe → verify expected_result
  → retry / replan on failure → verify final goal before finish.

Public closed-loop entry: neuron.brain.agent_loop.AgentLoop
"""

from __future__ import annotations

from typing import Any

from neuron.brain import executor
from neuron.brain import planner
from neuron.brain import recover
from neuron.brain import verifier
from neuron.brain.goal import GoalState
from neuron.brain.normalize import normalize_plan
from neuron.brain.step import DEFAULT_RETRY_LIMIT, DEFAULT_TIMEOUT, enrich_step_dict
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


def _step_timeout(step: dict, default: float) -> float:
    try:
        t = step.get("timeout")
        if t is None:
            return float(default)
        return float(t)
    except (TypeError, ValueError):
        return float(default)


def _step_retry_limit(step: dict, default: int) -> int:
    try:
        r = step.get("retry_limit")
        if r is None:
            return int(default)
        return max(0, int(r))
    except (TypeError, ValueError):
        return int(default)


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
    Execute a plan under closed-loop OPAVR.

    If plan is None, plans from request+context first.
    Returns (say, acted, meta, goal_state).
    """
    cfg = _cfg()
    max_retries = int(cfg.get("max_replans", 3) or 3)
    max_step_retries = int(cfg.get("max_step_retries", DEFAULT_RETRY_LIMIT) or DEFAULT_RETRY_LIMIT)
    max_iters = int(cfg.get("max_loop_iterations", 12) or 12)
    default_timeout = float(cfg.get("tool_timeout_seconds", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)
    strict = bool(cfg.get("strict_verify", True))
    verify_final = bool(cfg.get("verify_final_goal", True))

    tr = trace or Trace()
    meta: dict[str, Any] = {
        "path": "opavr",
        "replanned": False,
        "recovered": False,
        "steps": [],
        "needs_confirm": None,
        "diagnoses": [],
    }

    goal_text = (normalized or request or "").strip()
    tr.user(request)
    if observe_blob or context:
        tr.context(observe_blob or context[:800])

    try:
        from neuron.memory import scopes
        scopes.working().begin_task(goal_text)
    except Exception:
        pass

    # PLAN
    if plan is None:
        plan = planner.plan(request, context, normalized=normalized)
    if plan is None:
        meta["path"] = "plan_failed"
        tr.final("failed", "Planner unavailable")
        g = GoalState(goal=goal_text, status="failed", max_retries=max_retries)
        g.mark_failed("Planner returned no plan")
        try:
            from neuron.memory import scopes
            scopes.working().sync_goal_state(g)
        except Exception:
            pass
        return None, False, meta, g

    plan = normalize_plan(plan)
    # Ensure every step is fully enriched
    plan["steps"] = [
        enrich_step_dict(s, default_timeout=default_timeout, default_retry=max_step_retries)
        for s in (plan.get("steps") or [])
    ]
    goal = GoalState.from_plan(goal_text, plan, max_retries=max_retries)
    tr.plan(plan)
    try:
        from neuron.memory import scopes
        scopes.working().sync_goal_state(goal)
    except Exception:
        pass

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
        try:
            from neuron.speech import interrupt as interrupt_mod
            if interrupt_mod.interrupted():
                goal.status = "interrupted"
                if "Interrupted by user" not in (goal.errors or []):
                    goal.errors.append("Interrupted by user")
                goal.pending_steps = []
                say = "Stopped."
                tr.final("interrupted", say)
                meta["path"] = "interrupted"
                meta["interrupted"] = True
                meta["steps"] = list(goal.action_history)
                try:
                    from neuron.memory import scopes
                    scopes.working().sync_goal_state(goal)
                except Exception:
                    pass
                return say, True, meta, goal
        except Exception:
            pass

        step = enrich_step_dict(
            dict(goal.pending_steps[0]),
            default_timeout=default_timeout,
            default_retry=max_step_retries,
        )
        goal.pending_steps[0] = step  # keep enriched form
        per_step_retry_limit = _step_retry_limit(step, max_step_retries)
        timeout = _step_timeout(step, default_timeout)

        # OBSERVE (before act)
        hint = str(step.get("target") or (step.get("args") or {}).get("name") or goal.goal)
        world_before = verifier.observe_world(hint, step=step)
        goal.update_observation(world_before, note="pre-act")
        tr.observe(world_before, note="pre-act")
        if world_before.get("ui_change"):
            tr.diagnose({"ui_change_pre": world_before.get("ui_change")})
        try:
            from neuron.memory import scopes
            app = world_before.get("app") or world_before.get("active_application")
            if app:
                scopes.session().note_app(str(app))
            mid = world_before.get("focused_monitor")
            if mid is not None:
                scopes.session().note_monitor(mid)
            scopes.working().note_observation(
                f"pre-act app={app or '?'} monitor={mid if mid is not None else '?'}"
            )
        except Exception:
            pass

        # ACT — exactly ONE step
        tr.action(step)
        er = executor.execute_plan(
            {"say": "", "steps": [step]},
            confirmed=confirmed,
            timeout=timeout,
        )
        meta["steps"] = list(goal.action_history)

        if er.needs_confirm:
            goal.status = "needs_confirm"
            meta["needs_confirm"] = er.needs_confirm
            tr.result(False, er.needs_confirm.get("reason") or "confirm required")
            tr.final("needs_confirm", "Confirmation required")
            try:
                from neuron.memory import scopes
                scopes.working().sync_goal_state(goal)
            except Exception:
                pass
            return None, True, meta, goal

        entry = er.steps_run[-1] if er.steps_run else {
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": False,
            "out": (er.errors[-1] if er.errors else "no result"),
        }
        act_ok = bool(entry.get("ok")) and not er.errors
        tr.result(act_ok, entry.get("out") or "", ms=entry.get("ms"))
        try:
            from neuron.memory import scopes
            scopes.working().note_action(
                str(entry.get("action") or step.get("action") or "?"),
                ok=act_ok,
                detail=str(entry.get("out") or ""),
                args=entry.get("args") if isinstance(entry.get("args"), dict) else {},
            )
        except Exception:
            pass

        # OBSERVE RESULT + VERIFY (never assume success)
        world_after = verifier.observe_world(hint, step=step)
        goal.update_observation(world_after, note="post-act")
        tr.observe(world_after, note="post-act")
        try:
            from neuron.memory import scopes
            app = world_after.get("app") or world_after.get("active_application")
            if app:
                scopes.session().note_app(str(app))
            scopes.working().sync_goal_state(goal)
        except Exception:
            pass
        vr = verifier.verify_execution_step(step, entry, strict=strict)
        tr.verification(
            vr.ok,
            vr.note,
            expected=step.get("expected_result") or "",
            **(vr.evidence or {}),
        )

        if vr.ok and act_ok:
            goal.complete_current(step, entry, verify_note=vr.note)
            step_retries = 0
            meta["steps"] = list(goal.action_history)
            continue

        # Failure — diagnose, then retry / replan
        err = vr.note or (er.errors[-1] if er.errors else "verification failed")
        goal.fail_current(step, err, entry)
        diagnosis = verifier.diagnose_failure(step, err, world_after)
        meta["diagnoses"].append(diagnosis)
        tr.diagnose(diagnosis)

        # Per-step retry budget + global replan budget
        if step_retries >= per_step_retry_limit or not goal.bump_retry():
            goal.mark_failed(err)
            say = goal.honest_failure_message()
            tr.final("failed", say, cause=diagnosis.get("cause"))
            meta["steps"] = list(goal.action_history)
            return say, True, meta, goal

        step_retries += 1
        remaining = list(goal.pending_steps[1:])  # skip failed head

        # 1) Deterministic alternate method (one at a time)
        alt = recover.deterministic_recovery(step, err, goal)
        if alt:
            new_pending = recover.merge_recovery(step, remaining, [alt[0]])
            # Re-enrich recovery steps
            new_pending = [
                enrich_step_dict(s, default_timeout=default_timeout, default_retry=max_step_retries)
                for s in new_pending
            ]
            goal.set_pending(new_pending)
            meta["recovered"] = True
            tr.replan(f"deterministic recover ({diagnosis.get('cause')}): {err}", new_pending)
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
            say = (retry_plan or {}).get("say") if retry_plan else None
            say = (say or "").strip() or goal.honest_failure_message()
            goal.mark_failed(err)
            tr.replan(f"no recovery plan: {err}", [])
            tr.final("failed", say, cause=diagnosis.get("cause"))
            meta["steps"] = list(goal.action_history)
            return say, True, meta, goal

        new_steps = normalize_plan(retry_plan).get("steps") or []
        new_steps = [
            enrich_step_dict(s, default_timeout=default_timeout, default_retry=max_step_retries)
            for s in new_steps
        ]
        goal.set_pending(new_steps)
        if retry_plan.get("say"):
            goal.plan_say = str(retry_plan.get("say") or "")
        tr.replan(err, new_steps)
        step_retries = 0  # new plan gets a fresh per-step counter

    if goal.pending_steps:
        goal.mark_failed("Retry/iteration limit reached")
        say = goal.honest_failure_message()
        tr.final("failed", say)
        meta["steps"] = list(goal.action_history)
        return say, True, meta, goal

    # FINAL GOAL VERIFICATION — never finish without checking
    if verify_final and goal.completed_steps:
        final_vr = verifier.verify_goal(goal.goal or goal_text, goal, strict=strict)
        tr.verification(final_vr.ok, final_vr.note, phase="final_goal", **(final_vr.evidence or {}))
        if not final_vr.ok:
            # One recovery attempt for unmet final goal
            if goal.bump_retry():
                meta["replanned"] = True
                retry_plan = recover.llm_replan_pending(
                    request,
                    context,
                    goal,
                    goal.completed_steps[-1] if goal.completed_steps else {},
                    final_vr.note,
                    normalized=normalized,
                )
                if retry_plan and (retry_plan.get("steps") or []):
                    new_steps = [
                        enrich_step_dict(s, default_timeout=default_timeout, default_retry=max_step_retries)
                        for s in (normalize_plan(retry_plan).get("steps") or [])
                    ]
                    goal.set_pending(new_steps)
                    tr.replan(f"final goal unmet: {final_vr.note}", new_steps)
                    # Recurse into remaining iterations via outer while — but we're past it.
                    # Run a bounded secondary loop for final-goal recovery.
                    secondary = 0
                    while goal.pending_steps and secondary < max(1, max_iters // 2):
                        secondary += 1
                        iterations += 1
                        if iterations > max_iters:
                            break
                        step = enrich_step_dict(
                            dict(goal.pending_steps[0]),
                            default_timeout=default_timeout,
                            default_retry=max_step_retries,
                        )
                        goal.pending_steps[0] = step
                        hint = str(
                            step.get("target")
                            or (step.get("args") or {}).get("name")
                            or goal.goal
                        )
                        world_before = verifier.observe_world(hint)
                        goal.update_observation(world_before, note="final-recover-pre")
                        tr.action(step)
                        er = executor.execute_plan(
                            {"say": "", "steps": [step]},
                            confirmed=confirmed,
                            timeout=_step_timeout(step, default_timeout),
                        )
                        if er.needs_confirm:
                            goal.status = "needs_confirm"
                            meta["needs_confirm"] = er.needs_confirm
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
                        world_after = verifier.observe_world(hint)
                        goal.update_observation(world_after, note="final-recover-post")
                        vr = verifier.verify_execution_step(step, entry, strict=strict)
                        tr.verification(vr.ok, vr.note, **(vr.evidence or {}))
                        if vr.ok and act_ok:
                            goal.complete_current(step, entry, verify_note=vr.note)
                            continue
                        err = vr.note or "verification failed"
                        goal.fail_current(step, err, entry)
                        goal.mark_failed(err)
                        say = goal.honest_failure_message()
                        tr.final("failed", say)
                        meta["steps"] = list(goal.action_history)
                        return say, True, meta, goal

                    # Re-check final goal after recovery steps
                    if not goal.pending_steps:
                        final_vr2 = verifier.verify_goal(goal.goal or goal_text, goal, strict=strict)
                        tr.verification(
                            final_vr2.ok, final_vr2.note, phase="final_goal", **(final_vr2.evidence or {})
                        )
                        if not final_vr2.ok:
                            goal.mark_failed(final_vr2.note)
                            say = goal.honest_failure_message()
                            tr.final("failed", say)
                            meta["steps"] = list(goal.action_history)
                            return say, True, meta, goal
                else:
                    goal.mark_failed(final_vr.note)
                    say = goal.honest_failure_message()
                    tr.final("failed", say)
                    meta["steps"] = list(goal.action_history)
                    return say, True, meta, goal
            else:
                goal.mark_failed(final_vr.note)
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
    tr.final("success", say, completed=len(goal.completed_steps))
    meta["steps"] = list(goal.action_history)
    return say, True, meta, goal
