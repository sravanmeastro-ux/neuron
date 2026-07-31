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


def _ctx_task_done(status: str, say: str = "") -> None:
    try:
        from neuron.v3.context_engine import get_engine
        get_engine().on_task_completed(status, say or "")
    except Exception:
        pass


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
        "loop": "adaptive_v37",
        "phase": "understand",
        "loop_status": "RUNNING",
        "replanned": False,
        "recovered": False,
        "steps": [],
        "needs_confirm": None,
        "diagnoses": [],
        "recovery_decisions": [],
    }

    goal_text = (normalized or request or "").strip()
    tr.user(request)
    if observe_blob or context:
        tr.context(observe_blob or context[:800])

    # V3.7 UNDERSTAND — capture goal text (Intent already done upstream)
    meta["understood_goal"] = goal_text

    # V3 ContextEngine — load session context; start task lifecycle
    try:
        from neuron.v3.context_engine import get_engine
        if cfg.get("context_engine", True):
            _ctx = get_engine()
            _ctx.on_user_command(request)
            _ctx.on_task_started(goal_text)
            blob = _ctx.compact_for_planner(1000)
            if blob:
                context = (blob + ("\n\n" + context if context else "")).strip()
    except Exception:
        pass

    try:
        from neuron.memory import scopes
        scopes.working().begin_task(goal_text)
    except Exception:
        pass

    # PLAN
    if plan is None:
        # Split observation (untrusted) from NEURON context when tagged
        obs = ""
        ctx_for_plan = context or ""
        if "<<<UNTRUSTED_SCREEN_OR_PAGE_DATA>>>" in ctx_for_plan:
            # already quarantined in context — pass as observation too
            obs = ctx_for_plan
            ctx_for_plan = ""
        try:
            plan = planner.plan(
                request,
                ctx_for_plan,
                normalized=normalized,
                observation=obs,
                validate=True,
            )
        except TypeError:
            # Older mocks / callers without V3.6 kwargs
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
        _ctx_task_done("failed", "Planner unavailable")
        return None, False, meta, g

    plan = normalize_plan(plan)
    # V3.6 — validate every plan before execution (registry + safety)
    try:
        from neuron.v3.plan_validator import validate_plan
        vr = validate_plan(plan, allow_empty=True, require_structured=False)
        meta["plan_validation"] = {
            "ok": vr.ok,
            "reason": vr.reason,
            "errors": list(vr.errors)[:8],
            "warnings": list(vr.warnings)[:8],
        }
        if not vr.ok:
            say = (vr.plan.get("say") if vr.plan else None) or (
                "I couldn't build a safe plan for that."
            )
            meta["path"] = "plan_rejected"
            tr.final("failed", say)
            g = GoalState(goal=goal_text, status="failed", max_retries=max_retries)
            g.mark_failed("; ".join(vr.errors)[:300] or vr.reason)
            _ctx_task_done("failed", say)
            return say, True, meta, g
        plan = vr.plan
    except Exception as exc:
        print(f"[opavr] plan validation skipped: {exc}", flush=True)
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
        _ctx_task_done("success", say or "")
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
                meta["loop_status"] = "INTERRUPTED"
                meta["interrupted"] = True
                meta["steps"] = list(goal.action_history)
                try:
                    from neuron.memory import scopes
                    scopes.working().sync_goal_state(goal)
                except Exception:
                    pass
                _ctx_task_done("interrupted", say)
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
        meta["phase"] = "observe"
        hint = str(step.get("target") or (step.get("args") or {}).get("name") or goal.goal)
        world_before = verifier.observe_world(hint, step=step)
        goal.update_observation(world_before, note="pre-act")
        tr.observe(world_before, note="pre-act")
        if world_before.get("ui_change"):
            tr.diagnose({"ui_change_pre": world_before.get("ui_change")})
        try:
            from neuron.v3.context_engine import get_engine
            eng = get_engine()
            prev_fp = eng.world.observation_fingerprint
            eng.world.apply_observation(world_before)
            if prev_fp and prev_fp != eng.world.observation_fingerprint:
                eng.on_window_changed(world_before)
        except Exception:
            pass
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

        # V3.7 SAFETY CHECK — before ACT (does not weaken policy; may stop early)
        meta["phase"] = "safety_check"
        try:
            from neuron.safety import policy as safety_policy
            allowed, reason = safety_policy.allow(
                str(step.get("action") or ""),
                step.get("args") if isinstance(step.get("args"), dict) else {},
                confirmed=confirmed,
            )
            if not allowed:
                tier = "confirm"
                try:
                    tier = safety_policy.classify(
                        str(step.get("action") or ""),
                        step.get("args") if isinstance(step.get("args"), dict) else {},
                    ).tier
                except Exception:
                    pass
                if tier == "blocked" or "blocked" in (reason or "").lower():
                    goal.status = "blocked"
                    meta["loop_status"] = "BLOCKED"
                    meta["path"] = "blocked"
                    say = reason or "That action is blocked."
                    tr.final("blocked", say)
                    _ctx_task_done("blocked", say)
                    return say, True, meta, goal
                # confirm / high → needs user (same as executor confirm gate)
                from neuron.safety import confirm as confirm_mod
                payload = confirm_mod.request_confirm(
                    str(step.get("action") or ""),
                    step.get("args") if isinstance(step.get("args"), dict) else {},
                    reason,
                )
                goal.status = "needs_confirm"
                meta["needs_confirm"] = payload
                meta["loop_status"] = "NEEDS_USER"
                meta["path"] = "needs_confirm"
                tr.final("needs_confirm", "Confirmation required")
                _ctx_task_done("needs_confirm", "Confirmation required")
                return None, True, meta, goal
        except Exception as exc:
            print(f"[opavr] safety check skipped: {exc}", flush=True)

        # ACT — exactly ONE step
        meta["phase"] = "act"
        tr.action(step)
        try:
            from neuron.v3.context_engine import get_engine
            get_engine().on_action_attempted(
                str(step.get("action") or ""),
                step.get("args") if isinstance(step.get("args"), dict) else {},
            )
        except Exception:
            pass
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
            _ctx_task_done("needs_confirm", "Confirmation required")
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

        # OBSERVE RESULT + VERIFY (never assume success — e.g. Blender must be detected)
        meta["phase"] = "verify"
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
            try:
                from neuron.v3.context_engine import get_engine
                get_engine().on_action_verified(
                    str(entry.get("action") or step.get("action") or ""),
                    str(entry.get("out") or vr.note or ""),
                    world_after,
                    args=entry.get("args") if isinstance(entry.get("args"), dict) else {},
                )
            except Exception:
                pass
            continue

        # Failure — diagnose → decide → observe again path via next iteration
        meta["phase"] = "diagnose"
        err = vr.note or (er.errors[-1] if er.errors else "verification failed")
        goal.fail_current(step, err, entry)
        try:
            from neuron.v3.context_engine import get_engine
            get_engine().on_action_failed(
                str(entry.get("action") or step.get("action") or ""),
                err,
                world_after,
                args=entry.get("args") if isinstance(entry.get("args"), dict) else {},
            )
        except Exception:
            pass
        diagnosis = verifier.diagnose_failure(step, err, world_after)
        meta["diagnoses"].append(diagnosis)
        tr.diagnose(diagnosis)

        # Interrupted mid-step
        if entry.get("interrupted") or diagnosis.get("category") == "INTERRUPTED":
            goal.status = "interrupted"
            meta["loop_status"] = "INTERRUPTED"
            meta["path"] = "interrupted"
            meta["interrupted"] = True
            say = "Stopped."
            tr.final("interrupted", say, cause=diagnosis.get("cause"))
            _ctx_task_done("interrupted", say)
            return say, True, meta, goal

        # Probe alternate availability for decision (category-aware)
        alt_probe = recover.deterministic_recovery(
            step, err, goal, category=str(diagnosis.get("category") or "")
        ) or []
        try:
            from neuron.v3.loop_types import decide_recovery, map_goal_status
            decision = decide_recovery(
                diagnosis,
                step_retries=step_retries,
                max_step_retries=per_step_retry_limit,
                global_retries=goal.retry_count,
                max_global_retries=max_retries,
                has_alternate=bool(alt_probe),
            )
            meta["recovery_decisions"].append(decision.to_dict())
            meta["loop_status"] = decision.status
        except Exception as exc:
            print(f"[opavr] decide_recovery failed: {exc}", flush=True)
            decision = None

        if decision and decision.strategy == "blocked":
            goal.status = "blocked"
            say = decision.reason or err
            tr.final("blocked", say, cause=diagnosis.get("cause"))
            meta["path"] = "blocked"
            meta["steps"] = list(goal.action_history)
            _ctx_task_done("blocked", say)
            return say, True, meta, goal

        if decision and decision.strategy == "ask_user":
            goal.status = "needs_user"
            say = decision.ask_prompt or diagnosis.get("ask_prompt") or err
            tr.final("needs_user", say, cause=diagnosis.get("cause"))
            meta["path"] = "needs_user"
            meta["loop_status"] = "NEEDS_USER"
            meta["steps"] = list(goal.action_history)
            _ctx_task_done("needs_user", say)
            return say, True, meta, goal

        # Per-step retry budget + global replan budget
        if step_retries >= per_step_retry_limit or not goal.bump_retry():
            if goal.completed_steps:
                goal.status = "partial_success"
                meta["loop_status"] = "PARTIAL_SUCCESS"
            else:
                goal.mark_failed(err)
                meta["loop_status"] = "FAILED"
            say = goal.honest_failure_message()
            tr.final(goal.status, say, cause=diagnosis.get("cause"))
            meta["steps"] = list(goal.action_history)
            _ctx_task_done(goal.status, say)
            return say, True, meta, goal

        step_retries += 1
        remaining = list(goal.pending_steps[1:])  # skip failed head
        strategy = (decision.strategy if decision else "") or "alternate"

        # Same-step retry (transient) — re-queue failed step once
        if strategy == "retry":
            wait_step = {"action": "wait", "args": {"seconds": 1.0}}
            retry_pending = [
                enrich_step_dict(wait_step, default_timeout=default_timeout, default_retry=max_step_retries),
                enrich_step_dict(dict(step), default_timeout=default_timeout, default_retry=max_step_retries),
            ] + [
                enrich_step_dict(s, default_timeout=default_timeout, default_retry=max_step_retries)
                for s in remaining
            ]
            goal.set_pending(retry_pending)
            meta["recovered"] = True
            meta["loop_status"] = "RETRY"
            tr.replan(f"retry ({diagnosis.get('category') or diagnosis.get('cause')}): {err}", retry_pending)
            continue

        # 1) Deterministic alternate method (one at a time)
        if strategy in ("alternate", "replan", "") and alt_probe:
            new_pending = recover.merge_recovery(step, remaining, [alt_probe[0]])
            new_pending = [
                enrich_step_dict(s, default_timeout=default_timeout, default_retry=max_step_retries)
                for s in new_pending
            ]
            goal.set_pending(new_pending)
            meta["recovered"] = True
            meta["loop_status"] = "RETRY"
            tr.replan(
                f"deterministic recover ({diagnosis.get('category') or diagnosis.get('cause')}): {err}",
                new_pending,
            )
            continue

        # 2) LLM replan — remaining work only
        meta["replanned"] = True
        meta["loop_status"] = "NEEDS_REPLAN"
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
            if goal.completed_steps:
                goal.status = "partial_success"
                meta["loop_status"] = "PARTIAL_SUCCESS"
            else:
                goal.mark_failed(err)
                meta["loop_status"] = "FAILED"
            tr.replan(f"no recovery plan: {err}", [])
            tr.final(goal.status, say, cause=diagnosis.get("cause"))
            meta["steps"] = list(goal.action_history)
            _ctx_task_done(goal.status, say)
            return say, True, meta, goal

        new_steps = normalize_plan(retry_plan).get("steps") or []
        # V3.6 validate replan
        try:
            from neuron.v3.plan_validator import validate_plan
            vr_plan = validate_plan({"say": retry_plan.get("say") or "", "steps": new_steps})
            if vr_plan.ok:
                new_steps = vr_plan.plan.get("steps") or new_steps
            else:
                say = "; ".join(vr_plan.errors)[:200] or goal.honest_failure_message()
                goal.mark_failed(err)
                meta["loop_status"] = "FAILED"
                tr.final("failed", say, cause=diagnosis.get("cause"))
                _ctx_task_done("failed", say)
                return say, True, meta, goal
        except Exception:
            pass
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
        _ctx_task_done("failed", say)
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
                            _ctx_task_done("needs_confirm", "Confirmation required")
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
                        _ctx_task_done("failed", say)
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
                            _ctx_task_done("failed", say)
                            return say, True, meta, goal
                else:
                    goal.mark_failed(final_vr.note)
                    say = goal.honest_failure_message()
                    tr.final("failed", say)
                    meta["steps"] = list(goal.action_history)
                    _ctx_task_done("failed", say)
                    return say, True, meta, goal
            else:
                goal.mark_failed(final_vr.note)
                say = goal.honest_failure_message()
                tr.final("failed", say)
                meta["steps"] = list(goal.action_history)
                _ctx_task_done("failed", say)
                return say, True, meta, goal

    goal.mark_success()
    meta["loop_status"] = "SUCCESS"
    meta["phase"] = "complete"
    # Prefer last verified outcome over optimistic plan.say
    say = ""
    if goal.action_history:
        last = goal.action_history[-1]
        if last.get("ok") and last.get("out"):
            say = str(last["out"])
    say = say or goal.plan_say or "Done."
    tr.final("success", say, completed=len(goal.completed_steps))
    meta["steps"] = list(goal.action_history)
    _ctx_task_done("success", say)
    return say, True, meta, goal
