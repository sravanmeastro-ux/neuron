"""Domain skill workflow tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_imports_and_api():
    from neuron.skills import youtube, windows, browser, spotify, discord, files, blender
    assert callable(youtube.search)
    assert callable(youtube.play_result)
    assert callable(browser.open_tab)
    assert callable(windows.focus_app)
    assert callable(windows.move_to_monitor)
    assert callable(spotify.play)
    assert callable(discord.open_channel)
    assert callable(files.find)
    assert callable(files.open)
    assert callable(blender.open_project)
    print("OK skill APIs")


def test_registry_bootstrap():
    from neuron.brain import tool_registry
    tool_registry.reset_for_tests()
    import brain  # noqa: F401 — legacy executors
    tool_registry.ensure_bootstrapped()
    names = set(tool_registry.names())
    for n in (
        "youtube.search",
        "youtube.play_result",
        "youtube_search",
        "browser.open_tab",
        "windows.focus_app",
        "windows.move_to_monitor",
        "spotify.play",
        "discord.open_channel",
        "files.find",
        "files.open",
        "blender.open_project",
    ):
        assert n in names, f"missing skill tool {n}"
    spec = tool_registry.get("youtube.search")
    assert spec is not None
    assert "query" in (spec.args_schema or {})
    print("OK registry", len([n for n in names if "." in n]), "dotted skills")


def test_youtube_search_validation():
    from neuron.skills import youtube
    r = youtube.search("")
    assert not r.success
    print("OK youtube validation")


def test_windows_move_validation():
    from neuron.skills import windows
    r = windows.move_to_monitor("", 2)
    assert not r.success
    print("OK windows validation")


def test_files_find_empty():
    from neuron.skills import files
    r = files.find("")
    assert not r.success
    print("OK files validation")


def test_normalize_skill_aliases_preserve_registered_form():
    """When both dotted and underscore are registered, keep the caller's form."""
    from neuron.brain import tool_registry
    from neuron.brain.normalize import normalize_step
    tool_registry.reset_for_tests()
    import brain  # noqa
    tool_registry.ensure_bootstrapped()
    step = normalize_step({"tool": "youtube_search", "arguments": {"query": "x"}})
    assert step["action"] == "youtube_search"
    step2 = normalize_step({"tool": "youtube.search", "arguments": {"query": "x"}})
    assert step2["action"] == "youtube.search"
    # Both resolve to a callable tool
    assert tool_registry.get("youtube_search") is not None
    assert tool_registry.get("youtube.search") is not None
    print("OK normalize alias preserves registered form")


def test_executor_runs_skill():
    from neuron.brain import executor, tool_registry
    tool_registry.reset_for_tests()
    import brain  # noqa
    tool_registry.ensure_bootstrapped()
    er = executor.execute_plan({
        "steps": [{"action": "windows.get_monitors", "args": {}}],
    })
    assert er.steps_run, er.unknown
    assert er.steps_run[0]["action"] == "windows.get_monitors"
    assert er.steps_run[0]["ok"] is True
    print("OK executor skill", er.outcomes[0][:60] if er.outcomes else "ok")


def test_skill_prompt():
    import skills
    blob = skills.for_prompt()
    assert "youtube.search" in blob
    assert "DOMAIN SKILLS" in blob
    print("OK skill prompt")


if __name__ == "__main__":
    test_imports_and_api()
    test_registry_bootstrap()
    test_youtube_search_validation()
    test_windows_move_validation()
    test_files_find_empty()
    test_normalize_skill_aliases_preserve_registered_form()
    test_executor_runs_skill()
    test_skill_prompt()
    print("ALL skill tests passed")
