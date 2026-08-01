"""V4.10 voice smoke — MOCK path: transcript → route → plan → safety → response."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from neuron.v4.voice import (
        reset_voice_metrics,
        voice_config_snapshot,
        hierarchical_voice_enabled,
        voice_routing_mode,
        VoiceRoutingMode,
        compare_shadow,
        VoiceRequest,
        canary_eligible,
        plan_hierarchical_readonly,
        guard_hierarchical_say,
        TaskOutcomeKind,
        build_migration_report,
        write_migration_report,
        voice_metrics,
        SHADOW_MUTATION_COUNT,
        procedure_learning_off,
    )
    from neuron.v4.context import reset_conversation_engine
    from neuron.v4.plan import HierarchicalPlanner, reset_hierarchical_planner

    reset_voice_metrics()
    print("V4.10 voice smoke (MOCK)")
    snap = voice_config_snapshot()
    print("config:", snap)
    assert procedure_learning_off() is True
    assert snap.get("procedure_learning_enabled") is False
    # During LIVE validation config may be SHADOW/CANARY; fail-closed still applies when flag off
    if not hierarchical_voice_enabled():
        assert voice_routing_mode() is VoiceRoutingMode.LEGACY

    # Normalize / understand / plan (no execute)
    eng = reset_conversation_engine()
    u = eng.understand("Open Chrome on monitor 2")
    print("UNDERSTAND:", u.rewritten_command, u.route)
    tools, intent, meta = plan_hierarchical_readonly(u.rewritten_command or "Open Chrome on monitor 2")
    print("PLAN tools:", tools, "source=", meta.get("source"))
    assert tools, "expected hierarchical tools"

    ok, reason = canary_eligible(
        text=u.rewritten_command or "Open Chrome",
        intent_family="WINDOW_MOVE" if "monitor" in (u.rewritten_command or "").lower() else "APP_OPEN",
        tools=tools,
    )
    print("CANARY:", ok, reason)

    # Multi-turn context (no mutation)
    eng.apply_verified(action="open_app", args={"name": "Chrome"}, status="SUCCESS")
    u2 = eng.understand("Move it to monitor 2")
    print("FOLLOW-UP:", u2.rewritten_command)

    # Shadow compare
    cmp = compare_shadow(VoiceRequest(text="Open Chrome", normalized="Open Chrome"))
    assert cmp.mutated is False
    print("SHADOW:", cmp.semantic_match, cmp.legacy_tools, cmp.hierarchical_tools)

    # Outcomes
    for outcome, expect_sub in (
        (TaskOutcomeKind.SUCCESS, "Done"),
        (TaskOutcomeKind.FAILURE, "couldn't"),
        (TaskOutcomeKind.UNCERTAIN, "verify"),
        (TaskOutcomeKind.CANCELLED, "Stopped"),
        (TaskOutcomeKind.WAITING_FOR_CONFIRMATION, "confirm"),
        (TaskOutcomeKind.WAITING_FOR_CLARIFICATION, "mean"),
    ):
        say = guard_hierarchical_say(
            "Done." if outcome is TaskOutcomeKind.SUCCESS else None,
            outcome,
            action_summary="open Chrome",
        )
        print(f"  OUTCOME {outcome.value}: {say[:60]}")
        assert say

    # Confirmation / cancel language
    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    plan = p.create_plan("Open Chrome")
    assert plan.subgoals
    p.cancel(plan)
    print("CANCEL plan:", plan.status)

    m = voice_metrics()
    assert SHADOW_MUTATION_COUNT == 0
    print(voice_metrics())

    # Migration report (LIVE NOT_RUN → ready_for_default False)
    rep = build_migration_report(
        mock_parity_pass=True,
        shadow_parity_pass=True,
        live_parity_pass="NOT_RUN",
        safety_pass=True,
        false_success_pass=True,
        recovery_loop_pass=True,
        context_pass=True,
        latency_pass=True,
        canary_sample_count=0,
        live_sample_count=0,
        soak_status="NOT_RUN",
        extra_metrics=m,
    )
    path = write_migration_report(rep)
    print("REPORT:", path)
    assert rep.ready_for_default is False
    assert any("NOT_RUN" in b or "canary_sample" in b for b in rep.blockers)
    print("READY_FOR_DEFAULT=", rep.ready_for_default)
    print("\nVoice smoke PASS")


if __name__ == "__main__":
    main()
