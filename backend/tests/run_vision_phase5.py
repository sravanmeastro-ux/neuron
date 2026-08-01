"""Phase 5 vision / ScreenContext tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_screen_context_shape():
    from neuron.perception.screen_context import ScreenContext

    ctx = ScreenContext(
        monitor=1,
        application="Chrome",
        title="YouTube",
        visible_text=["Home", "Shorts"],
        ui_elements=[{"name": "Search", "control_type": "EditControl"}],
        vision_description="YouTube home feed",
        sources=["uia", "ocr"],
    )
    d = ctx.to_dict()
    assert d["application"] == "Chrome"
    assert d["visible_text"]
    assert "uia" in d["sources"]
    compact = ctx.compact()
    assert "YouTube" in compact
    print("OK ScreenContext", list(d.keys()))


def test_registry_phase5_tools():
    from neuron.brain import tool_registry
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    needed = [
        "capture_screen",
        "capture_monitor",
        "get_cursor_position",
        "get_active_window_screenshot",
        "ocr_image",
        "detect_text_regions",
        "analyze_screen",
        "get_screen_context",
    ]
    names = set(tool_registry.names())
    missing = [n for n in needed if n not in names]
    assert not missing, missing
    print("OK registry phase5", len(needed))


def test_cursor_position():
    from neuron.perception.capture_ops import get_cursor_position

    r = get_cursor_position({})
    assert r.success
    assert "x" in (r.state or {})
    print("OK cursor", r.message)


def test_active_window_screenshot():
    from neuron.perception.capture_ops import get_active_window_screenshot

    r = get_active_window_screenshot({})
    assert r.success, r.error
    path = Path((r.state or {}).get("path") or "")
    assert path.exists()
    title = str(r.state.get("title", "") or "")[:40].encode("ascii", "replace").decode("ascii")
    print("OK active screenshot", path.name, title.encode("ascii", "replace").decode("ascii") if isinstance(title, str) else title)


def test_pipeline_uia_first_no_vlm():
    from neuron.perception import pipeline

    with mock.patch.object(pipeline, "_local_vlm", return_value="SHOULD_NOT_CALL"):
        ctx = pipeline.build_screen_context(
            request="status",
            use_ocr=False,
            use_vlm=False,
        )
    assert "vlm" not in ctx.sources
    assert ctx.to_dict()["monitor"] >= 1
    print(
        "OK pipeline uia-first",
        ctx.sources,
        (ctx.application[:30] if ctx.application else "").encode("ascii", "replace").decode("ascii"),
    )


def test_analyze_screen_tool():
    from neuron.perception.pipeline import analyze_screen

    with mock.patch("neuron.perception.pipeline._local_vlm", return_value=""):
        r = analyze_screen({"request": "what is on screen", "use_ocr": False})
    assert r.success
    assert "state" in r.to_dict()
    print("OK analyze_screen", (r.message or "")[:80].replace("\n", " ").encode("ascii", "replace").decode("ascii"))


def test_ocr_regions_missing_path():
    from neuron.perception.ocr import detect_text_regions

    r = detect_text_regions({"path": "C:/no/such/file.png"})
    assert not r.success
    print("OK detect_text_regions validation")


if __name__ == "__main__":
    test_screen_context_shape()
    test_registry_phase5_tools()
    test_cursor_position()
    test_active_window_screenshot()
    test_pipeline_uia_first_no_vlm()
    test_analyze_screen_tool()
    test_ocr_regions_missing_path()
    print("\n=== Phase 5 vision tests passed ===")
