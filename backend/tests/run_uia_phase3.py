"""Phase 3 UI understanding tests — ranking, tools, registry."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_rank_settings_prefers_button():
    from neuron.uia.rank import rank_candidates
    from neuron.uia.types import ElementInfo

    candidates = [
        ElementInfo(name="Settings panel", control_type="PaneControl", depth=4, width=800, height=600, center_x=400, center_y=300),
        ElementInfo(name="Settings", control_type="ButtonControl", depth=2, width=80, height=24, center_x=100, center_y=40, automation_id="SettingsBtn"),
        ElementInfo(name="User Settings Help", control_type="TextControl", depth=3, width=200, height=16, center_x=200, center_y=80),
        ElementInfo(name="File", control_type="MenuItemControl", depth=1, width=40, height=20, center_x=30, center_y=10),
    ]
    ranked = rank_candidates(candidates, "Settings", prefer_clickable=True, limit=5)
    assert ranked, "expected matches"
    assert ranked[0].name == "Settings"
    assert ranked[0].control_type == "ButtonControl"
    assert ranked[0].score >= ranked[1].score
    print("OK rank Settings", ranked[0].score, ">", ranked[1].name, ranked[1].score)


def test_registry_phase3_tools():
    from neuron.brain import tool_registry
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    needed = [
        "get_ui_tree",
        "get_active_window_elements",
        "find_ui_element",
        "click_ui_element",
        "get_element_text",
        "get_element_bounds",
    ]
    names = set(tool_registry.names())
    missing = [n for n in needed if n not in names]
    assert not missing, missing
    doc = tool_registry.tools_doc(30)
    assert "click_ui_element" in doc
    print("OK registry phase3", len(needed))


def test_get_ui_tree_live():
    from neuron.uia.actions import get_ui_tree

    r = get_ui_tree({"depth": 3, "limit": 40})
    assert r.to_dict()["success"] in (True, False)
    if r.success:
        assert "elements" in r.state
        assert isinstance(r.state["elements"], list)
    print("OK get_ui_tree", (r.message or "")[:80].replace("\n", " | ").encode("ascii", "replace").decode("ascii"))


def test_find_with_mock_tree():
    from neuron.uia import actions
    from neuron.uia.types import ElementInfo
    from neuron.windows.result import ok

    win = ElementInfo(name="Demo App", control_type="WindowControl")
    elements = [
        ElementInfo(name="OK", control_type="ButtonControl", depth=2, width=60, height=24, center_x=50, center_y=50),
        ElementInfo(name="Settings", control_type="MenuItemControl", depth=1, width=70, height=22, center_x=120, center_y=12, automation_id="mnuSettings"),
    ]
    with mock.patch("neuron.uia.actions.ui_inspect.walk_elements", return_value=(win, elements)):
        r = actions.find_ui_element({"name": "Settings"})
    assert r.success
    assert r.state["element"]["name"] == "Settings"
    assert r.state["candidates"]
    print("OK find Settings", r.message)


def test_click_invoke_mocked():
    from neuron.uia import actions
    from neuron.uia.types import ElementInfo

    win = ElementInfo(name="Demo", control_type="WindowControl")
    el = ElementInfo(
        name="Settings",
        control_type="ButtonControl",
        depth=1,
        width=80,
        height=24,
        center_x=100,
        center_y=40,
        automation_id="SettingsBtn",
    )

    class FakeInvoke:
        def Invoke(self):
            return None

    class FakeCtrl:
        def GetInvokePattern(self):
            return FakeInvoke()

        def Click(self, simulateMove=False):
            raise RuntimeError("should not click")

        def Exists(self, *a):
            return True

    with mock.patch("neuron.uia.actions.ui_inspect.walk_elements", return_value=(win, [el])), mock.patch(
        "neuron.uia.actions._locate_control", return_value=FakeCtrl()
    ):
        r = actions.click_ui_element({"name": "Settings", "allow_vision_fallback": False})
    assert r.success
    assert "Clicked" in r.message
    assert r.state.get("method_detail") == "invoke"
    print("OK click invoke", r.method)


def test_verifier_click():
    from neuron.brain.verifier import verify_step

    ok, note = verify_step(
        {"action": "click_ui_element", "args": {"name": "Settings"}},
        "Clicked 'Settings'.",
        None,
    )
    assert ok
    bad, _ = verify_step(
        {"action": "click_ui_element", "args": {"name": "X"}},
        "Couldn't find UI element 'X'.",
        None,
    )
    assert not bad
    print("OK verifier click")


if __name__ == "__main__":
    test_rank_settings_prefers_button()
    test_registry_phase3_tools()
    test_get_ui_tree_live()
    test_find_with_mock_tree()
    test_click_invoke_mocked()
    test_verifier_click()
    print("\n=== Phase 3 UI tests passed ===")
