"""ComputerState unification tests — compose, don't duplicate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_computer_state_answers():
    from neuron.brain.computer_state import ComputerState

    cs = ComputerState(
        active_application="Chrome",
        focused_window_title="Blender fluid - YouTube - Google Chrome",
        focused_hwnd=42,
        focused_monitor=1,
        monitors=[
            {"monitor": 1, "app": "Chrome", "title": "YouTube - Google Chrome", "details": ["YouTube"]},
            {"monitor": 2, "app": "Discord", "title": "Discord", "details": ["Server list visible"]},
        ],
        open_windows=[
            {"title": "YouTube - Google Chrome", "monitor_id": 1, "app": "Chrome"},
            {"title": "Discord", "monitor_id": 2, "app": "Discord"},
        ],
        ui_elements=[
            {"name": "Save", "control_type": "ButtonControl", "center_x": 10, "center_y": 20, "enabled": True},
            {"name": "Cancel", "control_type": "ButtonControl", "center_x": 30, "center_y": 20, "enabled": True},
            {"name": "File", "control_type": "MenuItemControl", "center_x": 5, "center_y": 5, "enabled": True},
        ],
        browser_url="https://www.youtube.com/results?search_query=x",
        cursor={"x": 100, "y": 200, "monitor": 1},
        world_model_text="Monitor 1\nChrome\nYouTube\n",
    )
    cs.clickable_elements = [e for e in cs.ui_elements if "Button" in e["control_type"] or "Menu" in e["control_type"]]

    assert cs.looking_at() == "Chrome"
    assert cs.monitor_for_app("Chrome") == 1
    assert cs.monitor_for_app("Discord") == 2
    assert cs.focused_window()["hwnd"] == 42
    assert len(cs.clickables()) >= 2
    assert "Chrome" in cs.answer("What application am I looking at?")
    assert "monitor 1" in cs.answer("Which monitor contains Chrome?").lower()
    assert "Focused window" in cs.answer("What window currently has focus?")
    assert "clickable" in cs.answer("What clickable UI elements exist?").lower() or "Save" in cs.answer(
        "What clickable UI elements exist?"
    )
    print("OK answers", cs.looking_at(), cs.monitor_for_app("Discord"))


def test_ui_change_fingerprint():
    from neuron.brain.computer_state import ComputerState, set_last_state

    a = ComputerState(
        active_application="Chrome",
        focused_window_title="A",
        focused_hwnd=1,
        ui_elements=[{"name": "Save", "control_type": "ButtonControl"}],
    )
    b = ComputerState(
        active_application="Chrome",
        focused_window_title="B",
        focused_hwnd=1,
        ui_elements=[{"name": "Save", "control_type": "ButtonControl"}],
    )
    c = ComputerState(
        active_application="Chrome",
        focused_window_title="B",
        focused_hwnd=1,
        ui_elements=[{"name": "Export", "control_type": "ButtonControl"}],
    )
    d1 = b.changed_since(a)
    assert d1["changed"]
    assert any("focus_title" in x for x in d1["diffs"])
    d2 = c.changed_since(b)
    assert d2["changed"]
    assert any("uia_" in x for x in d2["diffs"])
    d3 = b.changed_since(b)
    assert not d3["changed"]

    set_last_state(a)
    set_last_state(b)
    assert "changed" in b.answer("Did the UI change after my last action?").lower()
    print("OK change detection", d1["reason"], d2["reason"])


def test_capture_composes_mocked():
    from neuron.brain import computer_state as cs_mod

    class Mon:
        def __init__(self, id, left=0, top=0, width=1920, height=1080, primary=True):
            self.id = id
            self.left = left
            self.top = top
            self.width = width
            self.height = height
            self.primary = primary

    fake_wm = {
        "text": "Monitor 1\nChrome\n\nActive application: Chrome\nFocused monitor: 1\nCursor position: 1,2\n",
        "monitors": [{"monitor": 1, "app": "Chrome", "title": "YouTube - Google Chrome", "details": ["YouTube"]}],
        "active_application": "Chrome",
        "active_window": "YouTube - Google Chrome",
        "focused_monitor": 1,
        "cursor": {"x": 1, "y": 2, "monitor": 1},
        "browser": {"url": "https://www.youtube.com/results", "site": "YouTube"},
    }

    class Snap:
        sticky_app = ""
        scene = "youtube"
        browser_url = "https://www.youtube.com/results"
        browser_title = "YouTube"
        browser_dom_summary = ""
        active_application = "Chrome"
        active_window = "YouTube - Google Chrome"
        monitor = 1
        visible_text = ["Home", "Shorts"]
        ui_elements = [
            {"name": "Home", "control_type": "ButtonControl"},
            {"name": "Shorts", "control_type": "ButtonControl"},
        ]
        sources = ["foreground", "uia"]

    with mock.patch("neuron.brain.world_model.build_world_model", return_value=fake_wm), mock.patch(
        "neuron.brain.snapshot.gather_snapshot", return_value=Snap()
    ), mock.patch(
        "neuron.windows.state.get_foreground",
        return_value={"title": "YouTube - Google Chrome", "hwnd": 99},
    ), mock.patch(
        "screen_capture.list_visible_windows",
        return_value=[{"title": "YouTube - Google Chrome", "monitor_id": 1, "hwnd": 99, "width": 100, "height": 100}],
    ), mock.patch.object(cs_mod, "_running_apps_light", return_value=[{"app": "Chrome", "process": "chrome.exe"}]):
        state = cs_mod.capture(deep=False, remember=True)

    assert state.looking_at() == "Chrome"
    assert state.focused_hwnd == 99
    assert state.browser_url.startswith("https://www.youtube.com")
    assert state.monitor_for_app("chrome") == 1
    obs = state.to_observe_dict()
    assert obs["computer_state"] is True
    assert obs["app"] == "Chrome"
    print("OK capture compose", state.looking_at(), state.fingerprint())


def test_observe_world_uses_computer_state():
    from neuron.brain import verifier
    from neuron.brain.computer_state import ComputerState

    cs = ComputerState(
        active_application="Notepad",
        focused_window_title="Untitled - Notepad",
        focused_hwnd=7,
        world_model_text="Monitor 1\nNotepad\n",
        cursor={"x": 9, "y": 9},
    )
    with mock.patch(
        "neuron.brain.computer_state.capture", return_value=cs
    ), mock.patch(
        "neuron.brain.computer_state.get_previous_state", return_value=None
    ):
        obs = verifier.observe_world("notepad")
    assert obs.get("app") == "Notepad" or obs.get("active_application") == "Notepad"
    assert obs.get("computer_state") is True
    print("OK observe_world ComputerState", obs.get("app"))


if __name__ == "__main__":
    test_computer_state_answers()
    test_ui_change_fingerprint()
    test_capture_composes_mocked()
    test_observe_world_uses_computer_state()
    print("\nComputerState tests passed.")
