"""V4.6 recovery smoke — MOCK progression, no live control.

Simulates failure → diagnose → recover → world update → verify → complete.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify.types import VerificationReport, VerificationEvidence
    from neuron.v4.recover import RecoveryEngine, RecoveryKind, reset_recovery_engine
    from neuron.v4.plan import HierarchicalPlanner, reset_hierarchical_planner
    from neuron.v4.world import DesktopWorldModel, reset_world_model

    reset_recovery_engine()
    reset_hierarchical_planner()
    reset_world_model()

    planner = HierarchicalPlanner()
    plan = planner.create_plan("click the search box")
    eng = RecoveryEngine()

    print("GOAL: click the search box")
    print(f"PLAN subgoals={len(plan.subgoals)}")

    # Fail: stale target
    print("\n--- FAIL: target stale ---")
    fail_rep = VerificationReport(
        status=VerificationOutcome.FAILURE,
        reason="element id missing",
        evidence=VerificationEvidence(facts={"revalidate": "MISSING"}),
    )
    d = eng.decide(
        verification=fail_rep,
        tool="click",
        args={"reference": "search box", "element_id": "abc"},
        reference="search box",
        resolution_status="NOT_FOUND",
        task_id=plan.plan_id,
    )
    print(f"DIAGNOSIS: {d.diagnosis.category.value if d.diagnosis else '?'}")
    print(f"DECISION: {d.kind.value} - {d.reason}")
    for a in d.actions:
        print(f"  ACTION: {a.kind.value} tool={a.tool} ref={a.reference}")

    eng.apply_to_plan(plan, d, planner=planner)
    print(f"PLAN status={plan.status.value}")

    # Mock world update after reobserve/reground
    print("\n--- WORLD UPDATE: new element ---")
    wm = DesktopWorldModel()
    wm.update_from_observe_dict({
        "active_application": "Chrome",
        "windows": [{"hwnd": 1, "title": "YouTube", "app": "Chrome", "focused": True, "monitor_id": 1,
                     "left": 0, "top": 0, "width": 800, "height": 600}],
        "monitors": [{"id": 1, "left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True}],
    })

    # Verify success after recovery path (caller verifies — recovery does not claim success)
    ok_rep = VerificationReport(status=VerificationOutcome.SUCCESS, reason="element clicked effect")
    eng.note_outcome(d, verification=ok_rep)
    from neuron.v4.types import VerificationOutcome as VO
    from neuron.v4.plan.types import PlanningDecision
    planner.apply_verification(
        plan,
        PlanningDecision(subgoal_id=plan.subgoals[0].subgoal_id),
        verification=VO.SUCCESS,
    )
    print(f"VERIFY: {ok_rep.status.value}")
    print(f"COMPLETE: plan_complete={planner.plan_is_complete(plan)}")

    # Blocked scenario print
    print("\n--- BLOCKED alternate ---")
    d2 = eng.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="blocked"),
        tool="run_shell",
        args={"command": "format c:"},
        legacy_diagnosis={"category": "POLICY_BLOCKED"},
    )
    print(f"DECISION: {d2.kind.value} strategy={d2.strategy}")

    print("\nRecovery smoke PASS (no live control).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
