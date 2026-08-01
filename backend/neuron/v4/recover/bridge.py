"""Bridge V3 diagnose_failure / decide_recovery ↔ V4 RecoveryEngine."""

from __future__ import annotations

from typing import Any

from neuron.v4.recover.engine import get_recovery_engine
from neuron.v4.recover.types import RecoveryDecision, RecoveryKind


def recover_from_verification(
    *,
    verification,
    step: dict[str, Any] | None = None,
    action_result: dict[str, Any] | None = None,
    world=None,
    task_id: str = "",
    interrupted: bool = False,
    state_changed: bool = False,
    legacy_diagnosis: dict[str, Any] | None = None,
) -> RecoveryDecision:
    """Primary OPAVR / AgentLoop entry for V4 recovery."""
    step = step or {}
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    eng = get_recovery_engine()
    return eng.decide(
        verification=verification,
        action_result=action_result or {},
        tool=str(step.get("action") or ""),
        args=args,
        expected_result=str(step.get("expected_result") or ""),
        reference=str(args.get("reference") or args.get("text") or args.get("name") or ""),
        element_id=str(args.get("element_id") or ""),
        world=world,
        world_before_fp=str(getattr(verification, "before_snapshot_id", "") or ""),
        world_after_fp=str(getattr(verification, "after_snapshot_id", "") or ""),
        interrupted=interrupted,
        task_id=task_id,
        action_id=str(getattr(verification, "action_id", "") or ""),
        subgoal_id=str(step.get("subgoal_id") or ""),
        target_app=str(args.get("name") or args.get("app") or ""),
        state_changed_since_fail=state_changed,
        legacy_diagnosis=legacy_diagnosis,
    )


def decision_to_legacy_steps(decision: RecoveryDecision, failed_step: dict | None = None) -> list[dict]:
    """Convert RecoveryDecision actions into OPAVR pending step dicts."""
    failed_step = failed_step or {}
    out: list[dict] = []
    for act in decision.actions:
        if act.kind in (RecoveryKind.REOBSERVE,):
            # OPAVR observes every loop iteration — encode as short wait
            out.append({"action": "wait", "args": {"seconds": 0.3}, "expected_result": "reobserve"})
            continue
        if act.kind is RecoveryKind.REGROUND:
            # Keep original step; reground happens via semantic resolve before act
            step = dict(failed_step)
            step["args"] = dict(step.get("args") or {})
            if act.reference:
                step["args"]["reference"] = act.reference
            step["_reground"] = True
            out.append(step)
            continue
        leg = act.to_legacy_step()
        if leg and leg.get("action"):
            out.append(leg)
    return out


def map_v3_decide(
    diagnosis: dict[str, Any],
    *,
    step_retries: int = 0,
    max_step_retries: int = 2,
    global_retries: int = 0,
    max_global_retries: int = 3,
    has_alternate: bool = False,
) -> RecoveryDecision:
    """Wrap v3 decide_recovery into V4 RecoveryDecision (compat)."""
    from neuron.v3.loop_types import decide_recovery

    v3 = decide_recovery(
        diagnosis,
        step_retries=step_retries,
        max_step_retries=max_step_retries,
        global_retries=global_retries,
        max_global_retries=max_global_retries,
        has_alternate=has_alternate,
    )
    kind_map = {
        "retry": RecoveryKind.RETRY,
        "alternate": RecoveryKind.ALTERNATE_TOOL,
        "replan": RecoveryKind.REPLAN,
        "ask_user": RecoveryKind.CLARIFY,
        "blocked": RecoveryKind.FAIL,
        "fail": RecoveryKind.FAIL,
    }
    return RecoveryDecision(
        kind=kind_map.get(v3.strategy, RecoveryKind.FAIL),
        reason=v3.reason,
        clarify_prompt=v3.ask_prompt,
        strategy=v3.strategy,
        v3_status=v3.status,
        confidence=0.6,
    )


__all__ = ["recover_from_verification", "decision_to_legacy_steps", "map_v3_decide"]
