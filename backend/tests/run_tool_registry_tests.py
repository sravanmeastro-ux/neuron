"""V3.5 ToolRegistry + CapabilityRouter tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_primitives_registered():
    from neuron.v3.tool_registry import PRIMITIVES, ensure_primitives, reset_for_tests
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    found = ensure_primitives()
    missing = [p for p in PRIMITIVES if p not in found]
    assert not missing, missing
    for name in ("open_app", "click_element", "speak", "verify", "wait"):
        spec = tr.get(name)
        assert spec is not None
        assert spec.description
        assert spec.risk
        assert callable(spec.handler)
    print("OK primitives", len(found))


def test_tool_has_schema_and_methods():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    spec = tr.get("open_app")
    assert spec.params.get("name", {}).get("required") is True
    assert "api" in (spec.control_methods or []) or "uia" in (spec.control_methods or [])
    browser = tr.get("browser_search")
    assert "dom" in (browser.control_methods or []) or "playwright" in (browser.control_methods or [])
    print("OK schema+methods", spec.to_dict()["params"])


def test_validate_args_ok_and_alias():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    ok, err, coerced = tr.validate_args("open_app", {"application": "Notepad"})
    assert ok, err
    assert coerced.get("name") == "Notepad"
    print("OK validate alias")


def test_validate_args_missing_required():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    ok, err, _ = tr.validate_args("type_text", {})
    assert not ok
    assert "text" in err.lower()
    print("OK missing required", err)


def test_validate_args_bad_type():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    ok, err, _ = tr.validate_args("wait", {"seconds": "nope"})
    # wait may coerce via float() failure
    assert not ok
    print("OK bad type", err)


def test_unknown_tool_rejected():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    assert not tr.is_registered("eval_python")
    assert not tr.is_registered("os.system")
    try:
        tr.execute("eval_python", {"code": "1+1"}, skip_policy=True)
        assert False, "should have raised"
    except ValueError as exc:
        assert "Unknown tool" in str(exc)
    print("OK unknown tool rejected")


def test_shell_hidden_from_planner():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    doc = tr.tools_doc(200)
    assert "run_shell" not in doc
    assert "run_powershell" not in doc
    assert "No shell/Python" in doc or "registered tools" in doc.lower()
    print("OK shell hidden from planner doc")


def test_executor_unknown_fails():
    from neuron.brain import executor, tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    er = executor.execute_plan({
        "say": "",
        "steps": [{"tool": "definitely_not_a_tool", "arguments": {}}],
    })
    assert er.errors
    assert er.unknown or "Unknown tool" in (er.errors[0] or "")
    print("OK executor rejects unknown")


def test_executor_invalid_args():
    from neuron.brain import executor, tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    er = executor.execute_plan({
        "say": "",
        "steps": [{"tool": "type_text", "arguments": {}}],
    })
    assert er.errors
    assert "text" in (er.errors[0] or "").lower()
    print("OK executor invalid args")


def test_volume_up_no_llm():
    from neuron.v3.capability_router import route

    r = route("volume up")
    assert r.ok, r.reason
    assert r.capability and r.capability.id == "system.volume"
    assert r.steps[0]["tool"] == "volume"
    assert r.steps[0]["arguments"].get("action") == "up"
    assert r.capability.control_method == "api"
    print("OK volume up deterministic")


def test_method_selection_domains():
    from neuron.v3.capability_router import choose_control_method

    m, fb = choose_control_method("browser")
    assert m == "dom"
    assert "coords" in fb or "playwright" in fb
    m2, _ = choose_control_method("files")
    assert m2 == "filesystem"
    m3, fb3 = choose_control_method("unknown_ui")
    assert m3 == "perception"
    assert "coords" in fb3
    m4, _ = choose_control_method("windows", browser_context=True)
    assert m4 == "dom"  # browser context promotes
    print("OK method selection", m, m2, m3, m4)


def test_click_fallback_tool_choice():
    from neuron.v3.capability_router import route

    with mock.patch(
        "neuron.v3.capability_router._browser_context", return_value=False
    ):
        r = route("click Settings")
    assert r.ok
    assert r.steps[0]["tool"] in ("click_element", "browser_click")
    with mock.patch(
        "neuron.v3.capability_router._browser_context", return_value=True
    ):
        r2 = route("click Settings")
    assert r2.ok
    assert r2.steps[0]["tool"] == "browser_click"
    print("OK click method fallback", r.steps[0]["tool"], r2.steps[0]["tool"])


def test_scroll_browser_fallback():
    from neuron.v3.capability_router import route

    with mock.patch(
        "neuron.v3.capability_router._browser_context", return_value=True
    ):
        r = route("scroll down")
    assert r.ok
    assert r.steps[0]["tool"] in ("browser_scroll", "scroll", "page_scroll")
    print("OK scroll tool", r.steps[0]["tool"])


def test_aliases_resolve():
    from neuron.brain import tool_registry as tr

    tr.reset_for_tests()
    tr.ensure_bootstrapped()
    assert tr.resolve_name("focus_window") == "focus_app" or tr.get("focus_window")
    assert tr.is_registered("open_url")
    assert tr.is_registered("find_file")
    assert tr.is_registered("inspect_screen")
    assert tr.is_registered("read_page")
    print("OK aliases")


if __name__ == "__main__":
    test_primitives_registered()
    test_tool_has_schema_and_methods()
    test_validate_args_ok_and_alias()
    test_validate_args_missing_required()
    test_validate_args_bad_type()
    test_unknown_tool_rejected()
    test_shell_hidden_from_planner()
    test_executor_unknown_fails()
    test_executor_invalid_args()
    test_volume_up_no_llm()
    test_method_selection_domains()
    test_click_fallback_tool_choice()
    test_scroll_browser_fallback()
    test_aliases_resolve()
    print("\nALL V3.5 ToolRegistry / CapabilityRouter tests passed")
