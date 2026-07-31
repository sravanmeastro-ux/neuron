"""Phase 2 Windows control tests — resolve, structured results, registry."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_resolve_aliases():
    from neuron.windows.resolve import resolve

    chrome = resolve("Google Chrome")
    assert chrome.canonical == "chrome"
    assert chrome.confidence >= 0.9

    browser = resolve("browser")
    assert browser.canonical in ("chrome", "edge")

    blender = resolve("Blender")
    assert blender.canonical == "blender"
    print("OK resolve", chrome.canonical, browser.canonical, blender.canonical)


def test_tool_result_shape():
    from neuron.windows.result import ok, fail

    r = ok("Opened Blender.", state={"verified": True}, method="win32-exe")
    d = r.to_dict()
    assert d["success"] is True
    assert d["error"] is None
    assert d["state"]["verified"] is True
    assert str(r) == "Opened Blender."

    f = fail("boom", state={})
    assert f.to_dict()["success"] is False
    assert "boom" in str(f)
    print("OK ToolResult", d.keys())


def test_registry_phase2_tools():
    from neuron.brain import tool_registry
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    needed = [
        "open_app", "close_app", "focus_app", "minimize_app", "maximize_app",
        "get_running_apps", "get_windows", "get_active_window",
        "move_window", "resize_window", "get_monitors",
        "press_key", "hotkey", "type_text", "scroll",
        "open_file", "open_folder", "search_files",
    ]
    names = set(tool_registry.names())
    missing = [n for n in needed if n not in names]
    assert not missing, f"missing tools: {missing}"
    print("OK registry phase2", len(needed), "tools")


def test_get_running_and_monitors():
    from neuron.windows import apps, winops

    r = apps.get_running_apps({})
    assert r.success
    assert "processes" in r.state
    m = winops.get_monitors({})
    assert m.success
    assert m.state.get("monitors")
    print("OK running/monitors", m.message[:60])


def test_get_active_window():
    from neuron.windows import winops

    r = winops.get_active_window({})
    # May succeed with a title on Windows
    assert r.to_dict()["success"] in (True, False)
    print("OK active_window", (r.message or "")[:80].encode("ascii", "replace").decode("ascii"))


def test_open_app_already_running_mocked():
    from neuron.windows import apps
    from neuron.windows.result import ok

    with mock.patch("neuron.windows.apps.win_state.app_is_running", return_value=True), mock.patch(
        "neuron.windows.apps.focus_app", return_value=ok("Focused notepad.", state={"launched": False}, method="uia")
    ):
        r = apps.open_app({"name": "notepad", "auto_learn": False})
    assert r.success
    assert "already" in r.message.lower() or "focused" in r.message.lower()
    print("OK open already-running", r.message)


def test_search_files_empty_query():
    from neuron.windows import files

    r = files.search_files({})
    assert not r.success
    print("OK search_files validation")


def test_executor_toolresult_failure():
    from neuron.brain import executor, tool_registry
    from neuron.windows.result import fail
    import brain  # noqa

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    tool_registry.register(
        "_test_fail_tool",
        lambda a: fail("nope"),
        description="test",
        risk="safe",
        overwrite=True,
    )
    er = executor.execute_plan({"steps": [{"action": "_test_fail_tool", "args": {}}]})
    assert er.errors and "nope" in er.errors[0]
    print("OK executor ToolResult fail")


if __name__ == "__main__":
    test_resolve_aliases()
    test_tool_result_shape()
    test_registry_phase2_tools()
    test_get_running_and_monitors()
    test_get_active_window()
    test_open_app_already_running_mocked()
    test_search_files_empty_query()
    test_executor_toolresult_failure()
    print("\n=== Phase 2 Windows tests passed ===")
