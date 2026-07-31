"""V3.3 ReferenceResolver tests — multi-turn context (no live desktop)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _seed_youtube_flow(eng):
    eng.on_user_command("open youtube")
    eng.on_action_attempted("open_website", {"site": "youtube"})
    eng.on_action_verified(
        "open_website",
        "Opened youtube",
        {
            "active_application": "Chrome",
            "window": "YouTube - Google Chrome",
            "url": "https://www.youtube.com/",
            "scene": "youtube",
        },
        args={"site": "youtube"},
    )
    eng.on_user_command("search youtube for blender tutorials")
    eng.on_action_attempted(
        "search_site", {"site": "youtube", "query": "blender tutorials"}
    )
    eng.on_action_verified(
        "search_site",
        "Searching YouTube for blender tutorials",
        {
            "active_application": "Chrome",
            "window": "blender tutorials - YouTube",
            "url": "https://www.youtube.com/results?search_query=blender",
            "scene": "youtube",
        },
        args={"site": "youtube", "query": "blender tutorials"},
    )


def test_play_the_first_one_after_youtube_search():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    _seed_youtube_flow(eng)
    r = resolve_reference("play the first one", engine=eng)
    assert not r.needs_clarification, r.clarification_prompt
    assert r.target_type == "video"
    assert r.args_hint.get("index") == 1
    assert "first" in (r.rewritten_command or "")
    assert r.confidence >= 0.55
    print("OK play the first one", r.rewritten_command, r.confidence)


def test_move_it_to_monitor_2_after_chrome():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    eng.on_user_command("open chrome")
    eng.on_action_attempted("open_app", {"name": "chrome"})
    eng.on_action_verified(
        "open_app",
        "Opened chrome",
        {
            "active_application": "Chrome",
            "window": "New Tab - Google Chrome",
            "focused_monitor": 1,
        },
        args={"name": "chrome"},
    )
    r = resolve_reference("move it to monitor 2", engine=eng)
    assert not r.needs_clarification, r.clarification_prompt
    assert "chrome" in (r.resolved_target or "").lower() or "Chrome" in r.resolved_target
    assert r.args_hint.get("monitor") in (2, "2", 2)
    assert "move" in (r.rewritten_command or "")
    print("OK move it", r.rewritten_command)


def test_close_it_with_clear_foreground():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    eng.world.apply_observation({
        "active_application": "Notepad",
        "window": "Untitled - Notepad",
        "fingerprint": "np1",
    })
    r = resolve_reference("close it", engine=eng)
    assert not r.needs_clarification, r.to_dict()
    assert "notepad" in r.resolved_target.lower()
    assert r.rewritten_command.startswith("close")
    print("OK close it", r.rewritten_command)


def test_close_it_ambiguous_clarifies():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    # Multiple recent apps, weak/empty active focus
    eng.on_action_attempted("open_app", {"name": "chrome"})
    eng.on_action_verified("open_app", "ok", {"active_application": "Chrome"}, args={"name": "chrome"})
    eng.on_action_attempted("open_app", {"name": "discord"})
    eng.on_action_verified("open_app", "ok", {"active_application": "Discord"}, args={"name": "discord"})
    eng.on_action_attempted("open_app", {"name": "spotify"})
    eng.on_action_verified("open_app", "ok", {"active_application": "Spotify"}, args={"name": "spotify"})
    # Clear verified focus to force entity competition
    eng.world.active_app = ""
    eng.world.active_window = ""
    r = resolve_reference("close it", engine=eng)
    assert r.needs_clarification, r.to_dict()
    assert r.candidates
    print("OK close ambiguous", r.clarification_prompt, r.candidates)


def test_do_that_again():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    eng.on_action_attempted("skip_ad", {})
    eng.on_action_verified("skip_ad", "Skipped the ad.", {"active_application": "Chrome"})
    r = resolve_reference("do that again", engine=eng)
    assert not r.needs_clarification
    assert r.target_type == "action"
    assert "skip" in (r.rewritten_command or "")
    print("OK do that again", r.rewritten_command)


def test_other_monitor():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    eng.world.apply_observation({
        "active_application": "Blender",
        "window": "Blender",
        "focused_monitor": 1,
    })
    r = resolve_reference("move it to the other monitor", engine=eng)
    assert not r.needs_clarification, r.to_dict()
    assert r.args_hint.get("monitor") == "other"
    print("OK other monitor", r.rewritten_command)


def test_search_that():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    eng.on_user_command("search youtube for fluid simulation")
    eng.on_action_verified(
        "search_site",
        "ok",
        {"scene": "youtube", "url": "https://youtube.com/results"},
        args={"site": "youtube", "query": "fluid simulation"},
    )
    r = resolve_reference("search that", engine=eng)
    assert not r.needs_clarification, r.to_dict()
    assert "fluid" in (r.resolved_target or r.args_hint.get("query") or "")
    print("OK search that", r.rewritten_command)


def test_downloaded_file():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    eng._note_file(r"C:\Users\me\Downloads\report.pdf")
    r = resolve_reference("open the file I just downloaded", engine=eng)
    assert not r.needs_clarification, r.to_dict()
    assert "report.pdf" in r.resolved_target
    print("OK downloaded file", r.rewritten_command)


def test_ui_candidates_hook():
    from neuron.v3.context_engine import reset_engine
    from neuron.v3.reference_resolver import resolve_reference

    eng = reset_engine()
    r = resolve_reference(
        "play the second one",
        engine=eng,
        ui_candidates=[
            {"label": "Intro to Blender", "type": "video"},
            {"label": "Geometry Nodes", "type": "video"},
            {"label": "Shading Tips", "type": "video"},
        ],
    )
    assert not r.needs_clarification
    assert r.resolved_target == "Geometry Nodes"
    assert r.args_hint.get("index") == 2
    assert r.source == "ui_candidates"
    print("OK ui candidates", r.resolved_target)


def test_no_deixis_passthrough():
    from neuron.v3.reference_resolver import resolve_reference
    r = resolve_reference("open notepad")
    assert not r.needs_clarification
    assert r.evidence == "no_deixis"
    print("OK passthrough")


def test_agent_integration_clarify(monkeypatch=None):
    """close it with no context → ask_user via agent.run"""
    from neuron.v3.context_engine import reset_engine
    from neuron.brain import agent as ag

    reset_engine()
    # empty world — should clarify
    say, acted, meta = ag.run("close it", use_rules_fallback=False)
    assert acted
    assert meta.get("path") == "ask_user" or meta.get("reference", {}).get("needs_clarification")
    print("OK agent clarify", meta.get("path"), say)


if __name__ == "__main__":
    test_play_the_first_one_after_youtube_search()
    test_move_it_to_monitor_2_after_chrome()
    test_close_it_with_clear_foreground()
    test_close_it_ambiguous_clarifies()
    test_do_that_again()
    test_other_monitor()
    test_search_that()
    test_downloaded_file()
    test_ui_candidates_hook()
    test_no_deixis_passthrough()
    test_agent_integration_clarify()
    print("\nALL ReferenceResolver tests passed")
