"""Phase 8 contextual computer understanding — snapshot + deixis resolver."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_snapshot_shape():
    from neuron.brain.snapshot import ContextSnapshot, infer_scene

    snap = ContextSnapshot(
        active_application="Chrome",
        active_window="Despacito - YouTube - Chrome",
        browser_url="https://www.youtube.com/results?search_query=despacito",
        browser_title="Despacito - YouTube",
        ui_elements=[
            {"name": "Despacito", "control_type": "Hyperlink"},
            {"name": "Shape of You", "control_type": "Hyperlink"},
        ],
        visible_text=["Despacito", "Shape of You", "Filters"],
    )
    snap.scene = infer_scene(snap)
    assert snap.scene == "youtube"
    blob = snap.compact()
    assert "youtube" in blob
    assert "Despacito" in blob
    d = snap.to_dict()
    assert d["browser_url"].startswith("https://")
    print("OK snapshot shape", snap.scene)


def test_youtube_first_one():
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import resolve

    snap = ContextSnapshot(
        active_window="YouTube - Chrome",
        browser_url="https://www.youtube.com/results?search_query=lofi",
        browser_title="lofi - YouTube",
        browser_dom_summary="[0] Lofi Hip Hop Radio | [1] Chill beats | [2] Study mix",
        ui_elements=[
            {"name": "Lofi Hip Hop Radio", "control_type": "link"},
            {"name": "Chill beats", "control_type": "link"},
            {"name": "Study mix", "control_type": "link"},
        ],
        visible_text=["Lofi Hip Hop Radio", "Chill beats", "Study mix"],
        scene="youtube",
    )
    r = resolve("Play the first one.", snap)
    assert r.ambiguous
    assert r.band == "high"
    assert r.references
    assert r.references[0].index == 0
    assert r.references[0].tool_hint == "browser_click"
    assert "Lofi" in r.rewritten_request or "index 0" in r.rewritten_request
    assert not r.ask_user
    print("OK youtube first one", r.rewritten_request, r.confidence)


def test_explorer_blender_one():
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import resolve

    snap = ContextSnapshot(
        active_application="File Explorer",
        active_window="Downloads",
        ui_elements=[
            {"name": "report.pdf", "control_type": "ListItem"},
            {"name": "Blender-4.2.0-windows-x64.msi", "control_type": "ListItem"},
            {"name": "notes.txt", "control_type": "ListItem"},
        ],
        visible_text=["report.pdf", "Blender-4.2.0-windows-x64.msi", "notes.txt"],
        scene="explorer",
    )
    r = resolve("Open the Blender one.", snap)
    assert r.ambiguous
    assert r.band == "high"
    assert "Blender" in (r.references[0].label or "")
    assert r.references[0].tool_hint == "click_ui_element"
    assert "Blender" in r.rewritten_request
    print("OK explorer blender", r.references[0].label, r.confidence)


def test_spotify_pause_it():
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import resolve

    snap = ContextSnapshot(
        active_application="Spotify",
        active_window="Spotify Premium",
        scene="spotify",
    )
    r = resolve("Pause it.", snap)
    assert r.ambiguous
    assert r.band == "high"
    assert r.references[0].entity_type == "playback"
    assert r.references[0].action_hint == "pause"
    assert r.references[0].tool_hint == "hotkey"
    print("OK spotify pause", r.rewritten_request)


def test_low_confidence_asks():
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import resolve

    snap = ContextSnapshot(scene="unknown", active_window="")
    r = resolve("Open that one.", snap)
    assert r.ambiguous
    assert r.band == "low"
    assert r.ask_user
    print("OK low ask", r.ask_user)


def test_destructive_never_guesses():
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import resolve

    snap = ContextSnapshot(
        active_window="Downloads",
        scene="explorer",
        ui_elements=[
            {"name": "a.txt", "control_type": "ListItem"},
            {"name": "b.txt", "control_type": "ListItem"},
        ],
        visible_text=["a.txt", "b.txt"],
    )
    r = resolve("Delete the first one.", snap)
    assert r.destructive_blocked
    assert r.band == "low"
    assert r.ask_user
    print("OK destructive blocked", r.ask_user[:60])


def test_ambiguous_detector():
    from neuron.brain.resolver import is_ambiguous

    assert is_ambiguous("Play the first one")
    assert is_ambiguous("Pause it")
    assert is_ambiguous("Open the Blender one")
    assert is_ambiguous("Close that window")
    assert not is_ambiguous("Open Notepad")
    assert not is_ambiguous("Search YouTube for lofi")
    print("OK deixis detector")


def test_agent_ask_user_path():
    from neuron.brain import agent
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import ResolveResult

    empty_snap = ContextSnapshot(scene="unknown")
    low = ResolveResult(
        ambiguous=True,
        confidence=0.2,
        band="low",
        ask_user="Which one did you mean — 'A'; 'B'?",
        rewritten_request="Open that one.",
    )
    with mock.patch("neuron.brain.snapshot.gather_snapshot", return_value=empty_snap), mock.patch(
        "neuron.brain.resolver.resolve", return_value=low
    ), mock.patch("neuron.brain.planner.plan") as plan_mock:
        say, acted, meta = agent.run("Open that one.", use_rules_fallback=False)
        assert meta.get("path") == "ask_user"
        assert acted
        assert "Which one" in (say or "")
        assert not plan_mock.called
    print("OK agent ask_user short-circuit")


def test_agent_high_confidence_rewrites():
    from neuron.brain import agent
    from neuron.brain.snapshot import ContextSnapshot
    from neuron.brain.resolver import ResolveResult, ResolvedReference
    from neuron.brain.verifier import VerifyResult
    from neuron.brain.executor import ExecutionResult

    snap = ContextSnapshot(scene="youtube", active_window="YouTube")
    high = ResolveResult(
        ambiguous=True,
        confidence=0.9,
        band="high",
        rewritten_request="Play the YouTube result 'Lofi Radio' (index 0)",
        resolved_blob="scene=youtube\n- 'first one' -> video:Lofi Radio conf=0.90",
        references=[
            ResolvedReference(
                phrase="first one",
                entity_type="video",
                label="Lofi Radio",
                index=0,
                confidence=0.9,
                tool_hint="browser_click",
                args_hint={"index": 0},
            )
        ],
    )
    captured = {}

    def fake_plan(request, context="", normalized=""):
        captured["request"] = request
        captured["context"] = context
        return {"say": "Playing.", "steps": [{"action": "browser_click", "args": {"index": 0}}]}

    er = ExecutionResult()
    er.outcomes = ["Clicked."]
    er.steps_run = [{
        "action": "browser_click",
        "args": {"index": 0},
        "ok": True,
        "out": "Clicked.",
    }]

    with mock.patch("neuron.brain.snapshot.gather_snapshot", return_value=snap), mock.patch(
        "neuron.brain.resolver.resolve", return_value=high
    ), mock.patch("neuron.brain.context.gather", return_value="CONTEXT_SNAPSHOT:\nscene=youtube"), mock.patch(
        "neuron.brain.planner.plan", side_effect=fake_plan
    ), mock.patch(
        "neuron.brain.executor.execute_plan", return_value=er
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step",
        return_value=VerifyResult(True, "ok"),
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world",
        return_value={"url": "https://youtube.com/watch"},
    ):
        say, acted, meta = agent.run("Play the first one.", use_rules_fallback=False)
        assert acted
        assert "Lofi" in captured.get("request", "") or "index 0" in captured.get("request", "")
        assert "RESOLVED_REFERENCES" in captured.get("context", "")
        assert meta.get("resolve", {}).get("band") == "high"
    print("OK agent high rewrite", captured.get("request"))


def test_gather_includes_snapshot():
    from neuron.brain import context as ctx_mod
    from neuron.brain.snapshot import ContextSnapshot

    snap = ContextSnapshot(
        active_window="Downloads",
        scene="explorer",
        ui_elements=[{"name": "Blender.msi", "control_type": "ListItem"}],
        visible_text=["Blender.msi"],
    )
    with mock.patch("neuron.brain.context.gather_snapshot", return_value=snap):
        text = ctx_mod.gather("open the blender one", snapshot=snap)
    assert "CONTEXT_SNAPSHOT" in text
    assert "explorer" in text or "Blender" in text
    print("OK gather snapshot section")


if __name__ == "__main__":
    test_snapshot_shape()
    test_youtube_first_one()
    test_explorer_blender_one()
    test_spotify_pause_it()
    test_low_confidence_asks()
    test_destructive_never_guesses()
    test_ambiguous_detector()
    test_agent_ask_user_path()
    test_agent_high_confidence_rewrites()
    test_gather_includes_snapshot()
    print("\nPhase 8 context tests passed.")
