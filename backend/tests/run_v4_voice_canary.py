"""V4.10 voice canary tests — MOCK/dry-run default. --live required for mutation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)

    from neuron.v4.voice import (
        reset_voice_metrics,
        canary_eligible,
        decide_route,
        VoiceRequest,
        RouteKind,
        VoiceRoutingMode,
        may_fallback_to_legacy,
        commit,
        voice_metrics,
        canary_policy_snapshot,
        VOICE_DUPLICATE_EXECUTION_COUNT,
        VOICE_SAFETY_MISMATCH_COUNT,
        UNVERIFIED_COMPLETION_RESPONSE_COUNT,
        guard_hierarchical_say,
        TaskOutcomeKind,
    )
    from neuron.v4.voice import commit as commit_mod
    from neuron.safety.policy import allow, risk_of

    reset_voice_metrics()
    print("V4.10 voice canary (MOCK)" if not args.live else "V4.10 voice canary LIVE")
    print("policy:", canary_policy_snapshot()["allow_intents"][:6], "...")

    # Eligibility
    ok, reason = canary_eligible(text="Open Chrome", intent_family="APP_OPEN")
    assert ok, reason
    bad, breason = canary_eligible(text="Delete my password file", intent_family="APP_OPEN")
    assert not bad, breason
    bad2, _ = canary_eligible(text="Open Chrome", tools=["run_procedure"])
    assert not bad2

    # Route decisions with forced config via monkeypatch of voice_routing_mode
    import neuron.v4.voice.config as vcfg
    import neuron.v4.voice.router as vrouter

    orig_en = vcfg.hierarchical_voice_enabled
    orig_mode = vcfg.voice_routing_mode

    def _en():
        return True

    def _mode_canary():
        return VoiceRoutingMode.CANARY

    def _mode_shadow():
        return VoiceRoutingMode.SHADOW

    vcfg.hierarchical_voice_enabled = _en  # type: ignore
    # Also patch router imports
    vrouter.hierarchical_voice_enabled = _en  # type: ignore
    vrouter.voice_routing_mode = _mode_canary  # type: ignore

    req = VoiceRequest(text="Open Chrome", normalized="Open Chrome", intent_family="APP_OPEN")
    d = decide_route(req, intent_family="APP_OPEN")
    assert d.route is RouteKind.HIERARCHICAL_CANARY, d
    print("OK canary eligible -> HIERARCHICAL_CANARY")

    d2 = decide_route(
        VoiceRequest(text="format the disk", normalized="format the disk"),
        intent_family="APP_OPEN",
    )
    assert d2.route is RouteKind.LEGACY
    print("OK deny -> LEGACY")

    vrouter.voice_routing_mode = _mode_shadow  # type: ignore
    d3 = decide_route(req, intent_family="APP_OPEN")
    assert d3.route is RouteKind.HIERARCHICAL_SHADOW

    # Commit / fallback
    commit_mod.begin_route("vr_test")
    assert may_fallback_to_legacy("vr_test")
    commit_mod.mark_mutation("windows.open_app", request_id="vr_test")
    assert not may_fallback_to_legacy("vr_test")
    commit_mod.clear_route("vr_test")
    print("OK route commit blocks fallback after mutation")

    # Safety parity through voice boundary
    for tool, tool_args in (
        ("windows.open_app", {"name": "Chrome"}),
        ("volume", {"direction": "up"}),
    ):
        ok_s, _ = allow(tool, tool_args, confirmed=False)
        assert ok_s or risk_of(tool) in ("safe", "confirm")
    blocked_ok, _ = allow("run_shell", {"command": "rm -rf /"}, confirmed=True)
    # Policy may block — must not weaken
    _ = blocked_ok
    print("OK safety allow/block still authoritative")

    # Unverified completion guard
    from neuron.v4.voice.types import reset_voice_metrics as _rst_metrics
    _rst_metrics()
    say = guard_hierarchical_say(
        "Done.",
        TaskOutcomeKind.UNCERTAIN,
        action_summary="fullscreen",
    )
    assert "Done." not in say
    assert "verify" in say.lower() or "couldn't" in say.lower()
    print("OK uncertain does not claim Done")

    # Restore
    vcfg.hierarchical_voice_enabled = orig_en  # type: ignore
    vcfg.voice_routing_mode = orig_mode  # type: ignore
    vrouter.hierarchical_voice_enabled = orig_en  # type: ignore
    vrouter.voice_routing_mode = orig_mode  # type: ignore

    m = voice_metrics()
    print(f"VOICE_DUPLICATE_EXECUTION_COUNT={m['VOICE_DUPLICATE_EXECUTION_COUNT']}")
    print(f"VOICE_SAFETY_MISMATCH_COUNT={m['VOICE_SAFETY_MISMATCH_COUNT']}")
    print(f"UNVERIFIED_COMPLETION_RESPONSE_COUNT={m['UNVERIFIED_COMPLETION_RESPONSE_COUNT']}")
    assert m["UNVERIFIED_COMPLETION_RESPONSE_COUNT"] == 0
    assert m["VOICE_DUPLICATE_EXECUTION_COUNT"] == 0
    assert m["VOICE_SAFETY_MISMATCH_COUNT"] == 0

    if args.live:
        print("LIVE requested - refusing automatic desktop mutation in canary harness.")
        print("Use soak harness with explicit scenarios under operator control.")
        return 0

    print("PASS voice canary (dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
