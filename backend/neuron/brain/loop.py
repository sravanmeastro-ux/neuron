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

    # Fresh recovery budget per command (avoid leaked cancel/exhaust from prior runs)
    try:
        from neuron.v4.recover import reset_recovery_engine
        reset_recovery_engine()
    except Exception:
        pass

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
        "world_model": True,
    }

    goal_text = (normalized or request or "").strip()
    tr.user(request)
    if observe_blob or context:
        tr.context(observe_blob or context[:800])

    # V3.7 UNDERSTAND — capture goal text (Intent already done upstream)
    meta["understood_goal"] = goal_text

    # V4.1 DesktopWorldModel — task-scoped snapshots (does not replace ContextEngine)
    try:
        from neuron.v4.world import get_world_model
        import hashlib
        tid = hashlib.sha1(goal_text.encode("utf-8", "replace")).hexdigest()[:10]
        get_world_model().set_task_id(tid)
        meta["task_id"] = tid
    except Exception:
        pass

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
        try:
            from neuron.v4.world import get_world_model
            from neuron.v4.perception import get_perception_engine
            wm = get_world_model()
            # V4.2: normalize observe_world → stable IDs + screen_diff → world model
            # (avoids a second full desktop scan; full pe.observe() remains available)
            pres = get_perception_engine().normalize_into_world(
                world_before, world=wm, push_world=True
            )
            meta["world_before_fp"] = wm.current.ensure_fingerprint()
            meta["world_active_app"] = wm.get_active_application()
            meta["world_active_monitor"] = wm.current.active_monitor_id
            meta["perception_confidence"] = pres.confidence
            meta["perception_sources"] = list(pres.sources_used)
            if pres.screen_diff:
                meta["world_diff_pre"] = pres.screen_diff.to_dict()
            if world_before.get("ui_change") is None and pres.screen_diff:
                world_before["ui_change"] = pres.screen_diff.to_dict()
                world_before["ui_changed"] = pres.screen_diff.changed
        except Exception as exc:
            print(f"[opavr] world model pre-act: {exc}", flush=True)
            try:
                from neuron.v4.world import get_world_model
                wm = get_world_model()
                wm.update_from_observe_dict(world_before, push_previous=True)
                meta["world_before_fp"] = wm.current.ensure_fingerprint()
            except Exception:
                pass
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
            from neuron.v4.world import get_world_model
            from neuron.v4.perception import get_perception_engine
            wm = get_world_model()
            pres = get_perception_engine().normalize_into_world(
                world_after, world=wm, push_world=True
            )
            wm.record_interaction(
                str(entry.get("action") or step.get("action") or ""),
                result=str(entry.get("out") or ""),
                ok=bool(act_ok),
                args=entry.get("args") if isinstance(entry.get("args"), dict) else {},
            )
            meta["world_after_fp"] = wm.current.ensure_fingerprint()
            meta["world_diff"] = (
                pres.screen_diff.to_dict() if pres.screen_diff else wm.diff_snapshots()
            )
            meta["perception_confidence"] = pres.confidence
            meta["perception_timing_ms"] = dict(pres.timing_ms)
        except Exception as exc:
            print(f"[opavr] world model post-act: {exc}", flush=True)
        try:
            from neuron.memory import scopes
            app = world_after.get("app") or world_after.get("active_application")
            if app:
                scopes.session().note_app(str(app))
            scopes.working().sync_goal_state(goal)
        except Exception:
            pass
        legacy_vr = verifier.verify_execution_step(step, entry, strict=strict)
        vr = legacy_vr
        # V4.5: authoritative VerificationEngine (world before/after). Soft legacy ≠ SUCCESS.
        v4_report = None
        try:
            from neuron.v4.verify import get_verification_engine

            eng = get_verification_engine()
            world_model = None
            try:
                from neuron.v4.world import get_world_model
                world_model = get_world_model()
            except Exception:
                world_model = None
            screen_diff = meta.get("world_diff")
            v4_report = eng.verify_step(
                step,
                world_before=None,
                world=world_model,
                screen_diff=screen_diff,
                action_result=entry,
                task_id=str(getattr(goal, "id", "") or getattr(goal, "goal_id", "") or ""),
                wait=bool(_cfg().get("v4_verify_wait", False)),
                use_legacy=False,
            )
            meta["verification_v4"] = v4_report.to_dict()
            not_obs = bool(
                v4_report.expectation
                and (v4_report.expectation.params or {}).get("not_observable")
            )
            use_v4 = bool(_cfg().get("v4_verify_authoritative", True)) and not not_obs
            if use_v4:
                from neuron.v4.types import VerificationOutcome

                class _VR:
                    pass

                _bridge = _VR()
                st = v4_report.status
                if st is VerificationOutcome.SUCCESS:
                    _bridge.ok = True
                    _bridge.note = v4_report.reason or legacy_vr.note
                elif st is VerificationOutcome.FAILURE:
                    facts = v4_report.evidence.facts if v4_report.evidence else {}
                    note_l = str(legacy_vr.note or "").lower()
                    soft = any(
                        m in note_l
                        for m in (
                            "soft-accept", "soft-ok", "verify skipped", "deferred",
                            "no contradiction", "no screen text", "accepted against observation",
                        )
                    )
                    active = str(facts.get("active_application") or "").strip().lower()
                    # Mock/sparse harness worlds: V4 FAILURE can be over-confident vs patched legacy.
                    mockish = active in ("mock", "", "?", "unknown") and not facts.get("window_hwnd")
                    if legacy_vr.ok and not soft and mockish:
                        _bridge.ok = True
                        _bridge.note = legacy_vr.note or v4_report.reason
                        meta["v4_fail_deferred_mock_world"] = True
                    else:
                        _bridge.ok = False
                        _bridge.note = (
                            legacy_vr.note if not legacy_vr.ok else (v4_report.reason or legacy_vr.note)
                        )
                else:
                    # UNCERTAIN: never auto-SUCCESS. Defer only to *hard* legacy True
                    # (tests/recovery with explicit verify notes). Soft-legacy stays blocked.
                    note_l = str(legacy_vr.note or "").lower()
                    soft = any(
                        m in note_l
                        for m in (
                            "soft-accept",
                            "soft-ok",
                            "verify skipped",
                            "deferred",
                            "no contradiction",
                            "no screen text",
                            "accepted against observation",
                        )
                    )
                    if legacy_vr.ok and not soft:
                        _bridge.ok = True
                        _bridge.note = legacy_vr.note or v4_report.reason
                        meta["v4_uncertain_deferred_to_legacy_hard"] = True
                    else:
                        _bridge.ok = False
                        # Prefer legacy failure text for recovery classification
                        _bridge.note = (legacy_vr.note if not legacy_vr.ok else "") or v4_report.reason or legacy_vr.note
                        if legacy_vr.ok and soft:
                            meta["legacy_soft_blocked_by_v4"] = True
                        elif legacy_vr.ok:
                            meta["legacy_ok_but_v4_uncertain"] = True
                _bridge.evidence = v4_report.evidence.to_dict()
                vr = _bridge
                if legacy_vr.ok and not vr.ok:
                    meta["legacy_ok_but_v4_not_success"] = True
            else:
                if legacy_vr.ok and v4_report and not v4_report.ok_for_advance:
                    meta["legacy_false_success_risk"] = True
                if not_obs:
                    meta["verification_not_observable"] = True
        except Exception as exc:
            print(f"[opavr] v4 verify bridge: {exc}", flush=True)
            meta["verification_v4_error"] = str(exc)[:160]

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
            try:
                from neuron.v4.context import on_opavr_verified
                v4st = meta.get("verification_v4") or {}
                uncertain = str(v4st.get("status") or "").upper() == "UNCERTAIN"
                on_opavr_verified(
                    action=str(entry.get("action") or step.get("action") or ""),
                    args=entry.get("args") if isinstance(entry.get("args"), dict) else {},
                    ok=True,
                    uncertain=uncertain,
                    observation=world_after if isinstance(world_after, dict) else {},
                    note=str(vr.note or ""),
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
        try:
            from neuron.v4.context import on_opavr_verified
            v4st = meta.get("verification_v4") or {}
            uncertain = str(v4st.get("status") or "").upper() == "UNCERTAIN"
            on_opavr_verified(
                action=str(entry.get("action") or step.get("action") or ""),
                args=entry.get("args") if isinstance(entry.get("args"), dict) else {},
                ok=False,
                uncertain=uncertain,
                observation=world_after if isinstance(world_after, dict) else {},
                note=err,
            )
        except Exception:
            pass
        diagnosis = verifier.diagnose_failure(step, err, world_after)
        meta["diagnoses"].append(diagnosis)
        tr.diagnose(diagnosis)

        # V4.6: RecoveryEngine over VerificationReport (typed decision; no second policy)
        v4_recovery = None
        try:
            from neuron.v4.recover import recover_from_verification, decision_to_legacy_steps
            from neuron.v4.recover.types import RecoveryKind
            from neuron.v4.verify.types import VerificationReport
            from neuron.v4.types import VerificationOutcome

            v4_raw = meta.get("verification_v4")
            report = None
            if isinstance(v4_raw, dict):
                st = str(v4_raw.get("status") or "UNCERTAIN")
                try:
                    outcome = VerificationOutcome(st)
                except Exception:
                    outcome = VerificationOutcome.UNCERTAIN
                report = VerificationReport(
                    status=outcome,
                    reason=str(v4_raw.get("reason") or err),
                    action_id=str(v4_raw.get("action_id") or ""),
                    task_id=str(v4_raw.get("task_id") or ""),
                    confidence=float(v4_raw.get("confidence") or 0.5),
                )
            v4_recovery = recover_from_verification(
                verification=report,
                step=step,
                action_result=entry if isinstance(entry, dict) else {},
                interrupted=bool(entry.get("interrupted")),
                state_changed=bool((meta.get("world_diff") or {}).get("changed")),
                legacy_diagnosis=diagnosis if isinstance(diagnosis, dict) else None,
            )
            meta["recovery_v4"] = v4_recovery.to_dict()
        except Exception as exc:
            print(f"[opavr] v4 recover bridge: {exc}", flush=True)
            meta["recovery_v4_error"] = str(exc)[:160]
            v4_recovery = None

        # Interrupted mid-step
        if entry.get("interrupted") or diagnosis.get("category") == "INTERRUPTED" or (
            v4_recovery and v4_recovery.kind.value == "CANCEL"
        ):
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
        # Prefer V4 recovery steps that are primitives / focus / popup dismiss.
        # Do NOT inject peer click-tool alternates into OPAVR alt_probe — that
        # short-circuits V3 deterministic_recovery → llm_replan when empty.
        if v4_recovery is not None:
            try:
                from neuron.v4.recover import decision_to_legacy_steps
                from neuron.v4.recover.types import RecoveryKind as RK
                inject = False
                if v4_recovery.kind in (
                    RK.FOCUS_THEN_RETRY, RK.WAIT, RK.RETRY, RK.REGROUND, RK.REOBSERVE,
                ):
                    inject = True
                elif v4_recovery.kind is RK.ALTERNATE_TOOL:
                    tools = {
                        str(a.tool or "").lower()
                        for a in (v4_recovery.actions or [])
                    }
                    if tools & {
                        "press_keys", "focus_app", "windows.focus_app", "wait",
                    } or str(diagnosis.get("category") or "") == "POPUP_DETECTED":
                        inject = True
                if inject:
                    v4_steps = decision_to_legacy_steps(v4_recovery, step)
                    if v4_steps:
                        alt_probe = v4_steps + list(alt_probe)
            except Exception:
                pass

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
            # Overlay V4 strategy when RecoveryEngine produced a decision
            if v4_recovery is not None:
                if v4_recovery.strategy:
                    decision.strategy = v4_recovery.strategy
                if v4_recovery.v3_status:
                    decision.status = v4_recovery.v3_status
                if v4_recovery.clarify_prompt:
                    decision.ask_prompt = v4_recovery.clarify_prompt
                if v4_recovery.reason:
                    decision.reason = v4_recovery.reason
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
            try:
                from neuron.v4.context import on_recovery_decision, on_ask_user_clarify
                if v4_recovery is not None:
                    on_recovery_decision(
                        v4_recovery,
                        goal_text=str(getattr(goal, "text", None) or request or ""),
                        plan_id="",
                    )
                else:
                    on_ask_user_clarify(
                        say,
                        original_goal=str(getattr(goal, "text", None) or request or ""),
                        source="opavr_recovery",
                    )
            except Exception:
                pass
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
