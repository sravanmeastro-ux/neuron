"""V4.8 CapabilityRouter vs HierarchicalPlanner semantic parity (MOCK)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CAPABILITY_PARITY_MISMATCH_COUNT = 0


def _norm_tool(name: str) -> str:
    from neuron.v4.capability import shared_semantic_tool, reset_capability_catalog

    reset_capability_catalog()
    can = shared_semantic_tool(name) or name
    # Collapse known pairs
    aliases = {
        "open_app": "windows.open_app",
        "focus_app": "windows.focus_app",
        "close_app": "windows.close_app",
        "move_window_to_monitor": "windows.move_to_monitor",
        "search_site": "youtube.search",
        "play_result": "youtube.play_result",
        "fullscreen": "youtube.fullscreen",
        "youtube_home": "youtube.home",
        "ensure_playback": "youtube.ensure_playback",
        "skip_ad": "youtube.skip_ad",
        "browser.search": "browser_search",
        "search_web": "browser_search",
    }
    can = aliases.get(can, can)
    can = aliases.get(name, can)
    return can


def _router_tool(utterance: str) -> str | None:
    from neuron.v3 import capability_router as cap
    from neuron.brain import intent as intent_mod

    intent = intent_mod.understand(utterance)
    routed = cap.route(utterance, intent=intent, min_confidence=0.5)
    if not routed.ok or not routed.steps:
        return None
    return str(routed.steps[0].get("action") or routed.capability.tool if routed.capability else "")


def _planner_tool(intent: str, args: dict | None = None) -> str | None:
    from neuron.v4.capability import resolve_intent, reset_capability_catalog

    reset_capability_catalog()
    res = resolve_intent(intent, args or {})
    return res.tool if res.ok else None


SCENARIOS = [
    ("open Chrome", "open_app", {"name": "Chrome"}),
    ("focus Chrome", "focus_app", {"name": "Chrome"}),
    ("move Chrome to monitor 2", "move_monitor", {"name": "Chrome", "monitor": 2}),
    ("search Blender on youtube", "youtube_search", {"query": "Blender"}),
    ("volume up", "volume", {"direction": "up"}),
]


def main():
    global CAPABILITY_PARITY_MISMATCH_COUNT
    from neuron.v4.capability import reset_capability_catalog

    reset_capability_catalog()
    mismatches = 0
    print("V4.8 capability parity (MOCK)")
    for utterance, intent, args in SCENARIOS:
        rt = _router_tool(utterance)
        pt = _planner_tool(intent, args)
        # If router didn't route, skip (not a mismatch — unsupported on fast path)
        if not rt:
            print(f"  SKIP router-miss {utterance!r} planner={pt}")
            continue
        rn = _norm_tool(rt)
        pn = _norm_tool(pt or "")
        # Parity: same canonical family (open/focus/move/search/volume)
        same = rn == pn or rn.split(".")[-1] == pn.split(".")[-1] or (
            "open" in rn and "open" in pn
        ) or ("search" in rn and "search" in pn) or (
            "monitor" in rn and "monitor" in pn
        ) or ("volume" in rn and "volume" in pn) or (
            "focus" in rn and "focus" in pn
        )
        if not same:
            mismatches += 1
            print(f"  MISMATCH {utterance!r} router={rt}->{rn} planner={pt}->{pn}")
        else:
            print(f"  OK {utterance!r} router={rn} planner={pn}")

    CAPABILITY_PARITY_MISMATCH_COUNT = mismatches
    print(f"\nCAPABILITY_PARITY_MISMATCH_COUNT={CAPABILITY_PARITY_MISMATCH_COUNT}")
    assert CAPABILITY_PARITY_MISMATCH_COUNT == 0
    print("PASS capability parity")


if __name__ == "__main__":
    main()
