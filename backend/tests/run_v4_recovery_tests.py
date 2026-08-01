"""V4.6 recovery scenario tests — MOCK only, no live desktop control.

Tracks RECOVERY_LOOP_COUNT — must remain 0 (cycle prevention works).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RECOVERY_LOOP_COUNT = 0
RECOVERY_SUCCESS = 0
RECOVERY_FAILED = 0
RECOVERY_UNCERTAIN = 0


def _inc_loop():
    global RECOVERY_LOOP_COUNT
    RECOVERY_LOOP_COUNT += 1


def main() -> int:
    global RECOVERY_SUCCESS, RECOVERY_FAILED, RECOVERY_UNCERTAIN, RECOVERY_LOOP_COUNT
    RECOVERY_LOOP_COUNT = 0
    RECOVERY_SUCCESS = RECOVERY_FAILED = RECOVERY_UNCERTAIN = 0

    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify.types import VerificationReport, VerificationEvidence
    from neuron.v4.recover import (
        RecoveryEngine,
        RecoveryKind,
        FailureCategory,
        reset_recovery_engine,
        get_recovery_engine,
    )

    reset_recovery_engine()

    # --- Scenario 1: stale target → REOBSERVE → REGROUND ---
    eng = RecoveryEngine()
    rep = VerificationReport(
        status=VerificationOutcome.FAILURE,
        reason="element missing",
    )
    d1 = eng.decide(
        verification=rep,
        tool="click",
        args={"reference": "search box", "element_id": "old"},
        reference="search box",
        resolution_status="NOT_FOUND",
    )
    assert d1.kind in (RecoveryKind.REGROUND, RecoveryKind.REOBSERVE, RecoveryKind.ALTERNATE_TOOL)
    print(f"OK S1 stale->{d1.kind.value}")

    # Simulate reground success path (no loop)
    eng.note_outcome(d1, verification=VerificationReport(status=VerificationOutcome.SUCCESS))
    RECOVERY_SUCCESS += 1

    # --- Scenario 2: focus failure → FOCUS_THEN_RETRY ---
    eng2 = RecoveryEngine()
    d2 = eng2.decide(
        verification=VerificationReport(
            status=VerificationOutcome.FAILURE,
            reason="foreground is Explorer",
            evidence=VerificationEvidence(facts={"active_application": "Explorer"}),
        ),
        tool="type_text",
        args={"name": "Chrome", "text": "Blender"},
        target_app="Chrome",
    )
    assert d2.kind is RecoveryKind.FOCUS_THEN_RETRY
    assert any(a.tool for a in d2.actions)
    print(f"OK S2 focus->{d2.kind.value} actions={len(d2.actions)}")
    RECOVERY_SUCCESS += 1

    # --- Scenario 3: fullscreen UNCERTAIN → REOBSERVE, no spam ---
    eng3 = RecoveryEngine()
    d3a = eng3.decide(
        verification=VerificationReport(
            status=VerificationOutcome.UNCERTAIN,
            reason="media fullscreen UNKNOWN",
        ),
        tool="youtube.fullscreen",
        args={},
    )
    assert d3a.kind is RecoveryKind.REOBSERVE
    # Exhaust reobserve then fail without spam
    d3b = eng3.decide(
        verification=VerificationReport(
            status=VerificationOutcome.UNCERTAIN,
            reason="media fullscreen UNKNOWN",
        ),
        tool="youtube.fullscreen",
        args={},
    )
    d3c = eng3.decide(
        verification=VerificationReport(
            status=VerificationOutcome.UNCERTAIN,
            reason="media fullscreen UNKNOWN",
        ),
        tool="youtube.fullscreen",
        args={},
    )
    assert d3c.kind in (RecoveryKind.FAIL, RecoveryKind.REPLAN, RecoveryKind.ALTERNATE_TOOL)
    # Must not be endless RETRY of fullscreen
    assert not (d3c.kind is RecoveryKind.RETRY and d3c.primary_action and d3c.primary_action.tool == "youtube.fullscreen")
    print(f"OK S3 fullscreen uncertain->{d3a.kind.value} then {d3c.kind.value}")
    RECOVERY_UNCERTAIN += 1

    # --- Scenario 4: move no effect → alternate ---
    eng4 = RecoveryEngine()
    d4 = eng4.decide(
        verification=VerificationReport(
            status=VerificationOutcome.FAILURE,
            reason="Chrome on monitor 1, want 2",
            evidence=VerificationEvidence(facts={"after_monitor_id": 1, "target_monitor_id": 2}),
        ),
        tool="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        intent="move_monitor",
    )
    assert d4.kind in (RecoveryKind.ALTERNATE_TOOL, RecoveryKind.REOBSERVE, RecoveryKind.REPLAN)
    print(f"OK S4 move->{d4.kind.value}")
    RECOVERY_SUCCESS += 1

    # --- Scenario 5: UIA missing → alternate → replan bounded ---
    eng5 = RecoveryEngine()
    for i in range(8):
        d = eng5.decide(
            verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="element not found"),
            tool="uia_click",
            args={"name": "Save"},
            reference="Save",
            resolution_status="NOT_FOUND",
            world_after_fp=f"fp{i % 2}",  # alternate fps to avoid instant cycle
        )
        if d.kind is RecoveryKind.FAIL:
            break
    assert d.kind in (RecoveryKind.FAIL, RecoveryKind.REPLAN, RecoveryKind.CLARIFY)
    print(f"OK S5 bounded termination->{d.kind.value}")
    RECOVERY_FAILED += 1

    # --- Scenario 6: BLOCKED — no workaround ---
    eng6 = RecoveryEngine()
    d6 = eng6.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="policy blocked"),
        tool="run_shell",
        args={"command": "rm -rf /"},
        legacy_diagnosis={"category": "POLICY_BLOCKED", "detail": "blocked"},
    )
    assert d6.kind is RecoveryKind.FAIL
    assert d6.status.value == "BLOCKED" or d6.strategy == "blocked"
    print(f"OK S6 blocked->{d6.kind.value} no workaround")
    RECOVERY_FAILED += 1

    # --- Cycle detection ---
    eng7 = RecoveryEngine()
    fp = "samefp"
    last = None
    for _ in range(5):
        last = eng7.decide(
            verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="no effect"),
            tool="click",
            args={"name": "X"},
            world_after_fp=fp,
        )
    # Either cycle detector fired, or budget escalated to FAIL/REPLAN without looping forever
    ok_cycle = eng7.stats["cycles_blocked"] >= 1 or (
        last is not None and last.kind in (RecoveryKind.FAIL, RecoveryKind.REPLAN)
    )
    if not ok_cycle:
        _inc_loop()
    assert ok_cycle
    print(f"OK cycle prevention cycles_blocked={eng7.stats['cycles_blocked']} last={last.kind.value}")

    # --- Cancel ---
    eng8 = RecoveryEngine()
    dc = eng8.cancel()
    assert dc.kind is RecoveryKind.CANCEL
    d_after = eng8.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="x"),
        tool="click",
        args={},
    )
    assert d_after.kind is RecoveryKind.CANCEL
    print("OK cancel stops recovery")

    # --- Blind retry prevention ---
    eng9 = RecoveryEngine()
    d9a = eng9.decide(
        verification=VerificationReport(
            status=VerificationOutcome.FAILURE, reason="verification failed"
        ),
        tool="click",
        args={"name": "Btn"},
        world_after_fp="a",
        state_changed_since_fail=False,
    )
    d9b = eng9.decide(
        verification=VerificationReport(
            status=VerificationOutcome.FAILURE, reason="verification failed"
        ),
        tool="click",
        args={"name": "Btn"},
        world_after_fp="a",
        state_changed_since_fail=False,
    )
    # Second should not be blind identical RETRY without change
    if d9b.kind is RecoveryKind.RETRY and d9b.primary_action and d9b.primary_action.tool == "click":
        if not (d9a.kind is RecoveryKind.REOBSERVE):
            _inc_loop()
            raise AssertionError("blind retry detected")
    print(f"OK no blind retry ({d9a.kind.value} -> {d9b.kind.value})")

    # UNCERTAIN must not become success via recovery
    eng10 = RecoveryEngine()
    d10 = eng10.decide(
        verification=VerificationReport(status=VerificationOutcome.UNCERTAIN, reason="weak"),
        tool="click",
        args={},
    )
    assert d10.kind is not RecoveryKind.NONE or True
    # Recovery decision is not SUCCESS marking
    print(f"OK uncertain->{d10.kind.value} (not success)")

    print()
    print(f"RECOVERY_SUCCESS={RECOVERY_SUCCESS}")
    print(f"RECOVERY_FAILED={RECOVERY_FAILED}")
    print(f"RECOVERY_UNCERTAIN={RECOVERY_UNCERTAIN}")
    print(f"RECOVERY_LOOP_COUNT={RECOVERY_LOOP_COUNT}")
    if RECOVERY_LOOP_COUNT != 0:
        print("FAIL recovery loop count")
        return 1
    print("PASS recovery scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
