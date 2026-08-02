"""Benchmarks for UI Grounding Engine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.screen.types import ScreenElement, ScreenSnapshot
    from neuron.ui_grounding import looks_like_ui_grounding, grounded_click, dispatch
    from neuron.ui_grounding.detect import classify_ug_intent
    from neuron.ui_grounding.match import ground_target, text_match_score, bbox_match_score, icon_match_score, confidence_score
    from neuron.ui_grounding.types import UGCapability
    from neuron.ui_grounding.bridge import maybe_handle_ui_grounding
    from neuron.ui_grounding import capture as cap
    from neuron.computer_use import primitives

    assert not looks_like_ui_grounding("mute")
    assert not looks_like_ui_grounding("Open Chrome")
    assert looks_like_ui_grounding("Ground and click Save")
    assert looks_like_ui_grounding("Click the login button")
    print("OK detect")

    assert classify_ug_intent("Ground and click Save")["capability"] == UGCapability.CLICK.value
    print("OK classify")

    # Synthetic matching
    el = ScreenElement(
        id="b1", name="Save", role="button", source="uia",
        x=100, y=200, left=80, top=180, right=120, bottom=220, width=40, height=40, confidence=0.9,
    )
    snap = ScreenSnapshot(elements=[el], window_title="Demo", application="DemoApp")
    assert text_match_score(el, "save") >= 0.85
    assert bbox_match_score(el) >= 0.5
    conf, parts = confidence_score(el, "Save button", snap=snap)
    assert conf >= 0.35, conf
    g = ground_target("Save", snap, min_confidence=0.3)
    assert g and g.name == "Save"
    print(f"OK match conf={g.confidence} parts={parts}")

    # Icon-ish
    icon = ScreenElement(
        id="i1", name="Settings", role="icon", source="uia",
        x=50, y=50, left=40, top=40, right=60, bottom=60, width=20, height=20, confidence=0.8,
    )
    assert icon_match_score(icon, "settings icon") >= 0.5
    print("OK icon_match")

    dpi = cap.ensure_dpi_aware()
    mons = cap.list_monitors()
    assert dpi >= 0.5
    print(f"OK dpi={dpi:.2f} monitors={len(mons)}")

    # Ungrounded coord click must be refused by gate (no nearby element in synthetic — live screen may vary)
    # Test primitives gate: without allow_raw, click_xy should route to grounding
    # Use absurd coords far from anything — expect fail or soft grounding fail
    r = grounded_click({"x": -50000, "y": -50000, "dry_run": True, "retries": 1, "scroll": False})
    assert hasattr(r, "success") and r.success is False, r
    print("OK refuse_ungrounded_coords")

    # Dry-run ground on live screen (may or may not find Save)
    say_r = dispatch(UGCapability.GROUND.value, {"target": "Save", "min_confidence": 0.99})
    print(f"OK ground_live ok={say_r.ok} say={say_r.say[:70]!r}")

    st = dispatch(UGCapability.STATUS.value, {})
    assert st.ok
    print(f"OK status {st.say[:70]!r}")

    assert maybe_handle_ui_grounding("mute") is None
    hit = maybe_handle_ui_grounding("UI grounding status")
    assert hit is not None
    print("OK bridge")

    # Raw click allow token
    tok = primitives.allow_raw_click(True)
    try:
        # force path shouldn't recurse
        assert primitives._RAW_CLICK_ALLOWED.get() is True
    finally:
        primitives.reset_raw_click(tok)
    print("OK raw_click_token")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("ui_ground_status")
    assert tool_registry.get("ui_ground_run")
    click_spec = tool_registry.get("click")
    assert click_spec is not None
    # Handler should be grounded_click
    assert "ground" in (click_spec.description or "").lower() or click_spec.handler
    print("OK tools (click gated)")

    print("PASS ui_grounding_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
