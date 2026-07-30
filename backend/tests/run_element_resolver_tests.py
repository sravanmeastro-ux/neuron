"""Element Resolver cascade tests — DOM → UIA → OCR → Vision → mouse."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_resolve_uia_then_act_mouse():
    from neuron.brain import element_resolver as er
    from neuron.windows.result import ok

    fake_el = {
        "name": "Search",
        "control_type": "ButtonControl",
        "center_x": 120,
        "center_y": 80,
        "automation_id": "searchBtn",
    }
    with mock.patch.object(er, "_browser_context", return_value=False), mock.patch(
        "neuron.uia.actions.find_ui_element",
        return_value=ok("Found Search", state={"element": fake_el}, method="uia"),
    ):
        target = er.resolve("Search", allow_ocr=False)
    assert target is not None
    assert target.source == "uia"
    assert target.name == "Search"
    assert target.x == 120 and target.y == 80

    class FakeCtrl:
        def GetInvokePattern(self):
            raise RuntimeError("no invoke")

        def Click(self, simulateMove=False):
            raise RuntimeError("no click")

    with mock.patch("neuron.uia.actions._locate_control", return_value=FakeCtrl()), mock.patch(
        "pyautogui.click"
    ) as clicked:
        # Force mouse path via coords after UIA bind fails patterns
        target.action_hint = "mouse"
        target.source = "ocr"  # exercise mouse act
        result = er.act(target)
    assert result.success
    clicked.assert_called_once_with(120, 80)
    print("OK uia resolve + mouse act", target.to_dict())


def test_click_cascade_dom_first():
    from neuron.brain import element_resolver as er
    from neuron.windows.result import ok, fail

    dom_el = {"name": "Search", "role": "button", "score": 90}
    with mock.patch.object(er, "_browser_context", return_value=True), mock.patch(
        "neuron.browser.agent.browser_find_element",
        return_value=ok("Found Search", state={"best": dom_el}, method="playwright-dom"),
    ), mock.patch(
        "neuron.browser.agent.browser_click",
        return_value=ok("Clicked 'Search'.", state={"url": "https://x"}, method="playwright:click"),
    ), mock.patch(
        "neuron.uia.actions.find_ui_element",
        return_value=fail("should not run"),
    ):
        result = er.click({"name": "Search", "allow_vision": False})
    assert result.success
    assert "resolver:dom" in (result.method or "")
    assert (result.state or {}).get("resolver_source") == "dom" or "dom" in (result.method or "")
    print("OK DOM-first click", result.method)


def test_click_falls_through_to_ocr():
    from neuron.brain import element_resolver as er
    from neuron.windows.result import fail, ok

    ocr_target = er.ResolvedTarget(
        query="Search",
        name="Search",
        x=50,
        y=60,
        source="ocr",
        confidence=0.7,
        action_hint="mouse",
    )
    with mock.patch.object(er, "_browser_context", return_value=False), mock.patch.object(
        er, "resolve_dom", return_value=None
    ), mock.patch.object(
        er, "resolve_uia", return_value=None
    ), mock.patch.object(
        er, "resolve_ocr", return_value=ocr_target
    ), mock.patch("pyautogui.click") as clicked:
        result = er.click({"name": "Search", "allow_vision": False})
    assert result.success
    clicked.assert_called_once_with(50, 60)
    assert "ocr" in (result.method or "")
    print("OK OCR fallthrough", result.method)


def test_click_ui_element_delegates_to_resolver():
    from neuron.uia import actions as uia_actions
    from neuron.windows.result import ok

    with mock.patch(
        "neuron.brain.element_resolver.click",
        return_value=ok("Clicked via resolver.", state={"resolver_source": "uia"}, method="resolver:uia:invoke"),
    ) as mocked:
        result = uia_actions.click_ui_element({"name": "Settings"})
    assert result.success
    mocked.assert_called_once()
    assert mocked.call_args[0][0]["name"] == "Settings"
    print("OK click_ui_element delegates")


def test_tool_registry_has_click_element():
    from neuron.brain import tool_registry
    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("click_element") is not None
    assert tool_registry.get("find_element") is not None
    assert tool_registry.get("click_ui_element") is not None
    print("OK registry click_element")


if __name__ == "__main__":
    test_resolve_uia_then_act_mouse()
    test_click_cascade_dom_first()
    test_click_falls_through_to_ocr()
    test_click_ui_element_delegates_to_resolver()
    test_tool_registry_has_click_element()
    print("\nElement Resolver tests passed.")
