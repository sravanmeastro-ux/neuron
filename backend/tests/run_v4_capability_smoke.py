"""V4.8 capability smoke — MOCK Goal→intent→capability→verify→recovery."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from neuron.v4.capability import (
        reset_capability_catalog,
        resolve_intent,
        coverage_report,
        get_capability_catalog,
    )
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify.types import VerificationReport

    print("V4.8 capability smoke (MOCK / no live control)")
    cat = reset_capability_catalog()
    rep = coverage_report()
    print(f"CATALOG total={rep['total']} shared={len(rep['shared'])} "
          f"legacy_only={rep['LEGACY_ONLY_CAPABILITY_COUNT']} "
          f"dup={rep['DUPLICATE_CAPABILITY_IMPLEMENTATION_COUNT']}")

    print("\n--- Goal: open Chrome ---")
    res = resolve_intent("open_app", {"name": "Chrome"})
    print("RESOLVE:", res.tool, res.verification_kind, res.reason)
    ga = res.to_grounded_action(intent="open_app", expected_result="Chrome open")
    print("GROUNDED:", ga.tool if ga else None, getattr(ga, "capability_id", ""))
    # Mock verify SUCCESS
    cat.note_outcome(res.tool, exec_ok=True, verify="SUCCESS", intent="open_app")
    print("VERIFY: SUCCESS")

    print("\n--- Primary fails -> alternate ---")
    res2 = resolve_intent("youtube_search", {"query": "Blender"})
    print("PRIMARY:", res2.tool)
    cat.note_outcome(res2.tool, exec_ok=True, verify="FAILURE", intent="youtube_search")
    alt = resolve_intent("youtube_search", {"query": "Blender"}, tried={res2.tool})
    print("ALTERNATE:", alt.tool, "ok=", alt.ok)
    assert alt.ok
    if alt.tool == res2.tool:
        print("(same tool acceptable if sole candidate)")
    cat.note_outcome(alt.tool, exec_ok=True, verify="SUCCESS", intent="youtube_search")
    print("VERIFY alternate: SUCCESS")

    print("\n--- Unsupported ---")
    bad = resolve_intent("teleport_to_mars", {})
    print("UNSUPPORTED:", bad.unsupported, bad.reason)
    assert bad.unsupported

    print("\nCapability smoke PASS")


if __name__ == "__main__":
    main()
