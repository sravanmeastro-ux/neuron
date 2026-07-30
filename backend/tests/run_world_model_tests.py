"""World-model format tests — multi-monitor AgentLoop observation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_format_world_model_shape():
    from neuron.brain.world_model import format_world_model

    text = format_world_model({
        "monitors": [
            {
                "monitor": 1,
                "app": "Chrome",
                "details": [
                    "YouTube",
                    "Search results visible",
                    "First video at approximately 420,310",
                ],
            },
            {
                "monitor": 2,
                "app": "Discord",
                "details": ["Server list visible"],
            },
        ],
        "active_application": "Chrome",
        "focused_monitor": 1,
        "cursor": {"x": 500, "y": 400},
    })
    assert "Monitor 1" in text
    assert "Chrome" in text
    assert "YouTube" in text
    assert "Search results visible" in text
    assert "First video at approximately 420,310" in text
    assert "Monitor 2" in text
    assert "Discord" in text
    assert "Server list visible" in text
    assert "Active application: Chrome" in text
    assert "Focused monitor: 1" in text
    assert "Cursor position: 500,400" in text
    print("OK format\n" + text)


def test_app_from_title():
    from neuron.brain.world_model import _app_from_title, _site_from_title_or_url

    assert _app_from_title("Lo-fi hip hop - YouTube - Google Chrome") == "Chrome"
    assert _site_from_title_or_url("YouTube - Google Chrome", "https://www.youtube.com/results?search_query=x") == "YouTube"
    assert _app_from_title("Discord") == "Discord"
    print("OK app/site infer")


def test_build_world_model_mocked():
    from neuron.brain import world_model as wm

    class Mon:
        def __init__(self, id, left=0, top=0, width=1920, height=1080, primary=True):
            self.id = id
            self.left = left
            self.top = top
            self.width = width
            self.height = height
            self.primary = primary

    wins = [
        {"title": "Blender fluid - YouTube - Google Chrome", "monitor_id": 1, "width": 1800, "height": 1000},
        {"title": "Discord", "monitor_id": 2, "width": 1400, "height": 900},
    ]
    with mock.patch("screen_capture.list_monitors", return_value=[
        Mon(1, primary=True),
        Mon(2, left=1920, primary=False),
    ]), mock.patch("screen_capture.list_visible_windows", return_value=wins), mock.patch.object(
        wm, "_browser_hints", return_value={
            "url": "https://www.youtube.com/results?search_query=blender",
            "site": "YouTube",
            "search_results": True,
            "first_video": {"x": 420, "y": 310, "visible": True},
        }
    ), mock.patch.object(wm, "_active_app_window", return_value=("Chrome", wins[0]["title"], 1)), mock.patch.object(
        wm, "_cursor", return_value={"x": 100, "y": 200, "monitor": 1}
    ), mock.patch("monitor_focus.get_focus", return_value=1):
        model = wm.build_world_model(deep=False)
    text = model["text"]
    assert "Monitor 1" in text and "Chrome" in text and "YouTube" in text
    assert "Search results visible" in text
    assert "First video at approximately 420,310" in text
    assert "Monitor 2" in text and "Discord" in text
    assert "Active application: Chrome" in text
    print("OK build mocked\n" + text)


if __name__ == "__main__":
    test_format_world_model_shape()
    test_app_from_title()
    test_build_world_model_mocked()
    print("\nWorld model tests passed.")
