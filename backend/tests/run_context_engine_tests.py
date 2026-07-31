"""V3.2 ContextEngine + WorldState tests (no live desktop required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_context_creation():
    from neuron.v3.context_engine import ContextEngine, reset_engine
    eng = reset_engine()
    assert isinstance(eng, ContextEngine)
    assert eng.world.task_status == "idle"
    assert eng.world.active_app == ""
    print("OK context creation")


def test_verified_vs_attempted():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.on_task_started("open blender")
    eng.on_action_attempted("open_app", {"name": "Blender"})
    # Attempt must NOT claim Blender is active
    assert eng.world.active_app == "", eng.world.active_app
    assert eng.world.pending_attempt is not None
    assert eng.world.pending_attempt.action == "open_app"

    # Only observation/verification updates confirmed focus
    eng.on_action_verified(
        "open_app",
        "Opened Blender",
        observation={
            "active_application": "Blender",
            "window": "Blender",
            "focused_monitor": 1,
            "url": "",
        },
        args={"name": "Blender"},
    )
    assert eng.world.active_app == "Blender"
    assert eng.world.pending_attempt is None
    assert eng.world.last_verified is True
    print("OK verified vs attempted")


def test_failed_action_does_not_fake_success_app():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.on_action_attempted("open_app", {"name": "Blender"})
    # Observation still shows Cursor — Blender did not open
    eng.on_action_failed(
        "open_app",
        "Couldn't find Blender",
        observation={
            "active_application": "Cursor",
            "window": "fillo jarvis - Cursor",
            "focused_monitor": 1,
        },
    )
    assert eng.world.active_app == "Cursor"
    assert eng.world.last_verified is False
    assert eng.world.pending_attempt is None
    print("OK failed action uses observation only")


def test_recent_entity_tracking():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.on_action_attempted("open_app", {"name": "Chrome"})
    eng.on_action_attempted("open_website", {"site": "youtube"})
    eng.on_action_attempted("open_folder", {"location": "downloads"})
    kinds = {e.kind for e in eng.recent_entities}
    names = {e.name.lower() for e in eng.recent_entities}
    assert "app" in kinds
    assert "chrome" in names
    assert any("youtube" in n for n in names)
    assert "downloads" in names or "folder" in kinds
    print("OK entity tracking", list(eng.recent_entities)[-3:])


def test_task_lifecycle():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.on_user_command("open notepad")
    eng.on_task_started("open notepad")
    assert eng.world.task_status == "running"
    assert eng.world.current_goal == "open notepad"
    eng.on_action_attempted("open_app", {"name": "notepad"})
    eng.on_action_verified(
        "open_app",
        "Opened notepad",
        {"active_application": "Notepad", "window": "Untitled - Notepad"},
    )
    eng.on_task_completed("success", "Opened notepad")
    assert eng.world.task_status == "success"
    assert len(eng.task_results) == 1
    assert len(eng.recent_commands) >= 1
    print("OK task lifecycle")


def test_session_reset():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.on_user_command("hello")
    eng.on_task_started("x")
    eng.on_action_attempted("open_app", {"name": "chrome"})
    eng.world.apply_observation({"active_application": "Chrome", "window": "x"})
    eng.reset_session()
    assert eng.world.active_app == ""
    assert len(eng.recent_commands) == 0
    assert len(eng.recent_actions) == 0
    assert eng.world.task_status == "idle"
    print("OK session reset")


def test_bounded_history():
    from neuron.v3.context_engine import ContextEngine, reset_engine
    eng = reset_engine()
    for i in range(ContextEngine.MAX_COMMANDS + 10):
        eng.on_user_command(f"command number {i}")
    assert len(eng.recent_commands) == ContextEngine.MAX_COMMANDS
    for i in range(ContextEngine.MAX_ACTIONS + 5):
        eng.on_action_attempted("wait", {"seconds": 1})
        eng.on_action_verified("wait", "ok", {"active_application": "X"})
    assert len(eng.recent_actions) == ContextEngine.MAX_ACTIONS
    print("OK bounded history", len(eng.recent_commands), len(eng.recent_actions))


def test_sensitive_filtering():
    from neuron.v3.context_engine import reset_engine, scrub_text
    assert "[redacted]" in scrub_text("password=hunter2 please")
    eng = reset_engine()
    eng.on_action_attempted("type_text", {"password": "hunter2", "text": "hello"})
    assert eng.world.pending_attempt is not None
    assert eng.world.pending_attempt.args.get("password") == "[redacted]"
    assert eng.world.pending_attempt.args.get("text") == "hello"
    print("OK sensitive filtering")


def test_window_changed_event():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.world.apply_observation({
        "active_application": "Chrome",
        "window": "A",
        "fingerprint": "fp1",
    })
    eng.on_window_changed({
        "active_application": "Notepad",
        "window": "B",
        "fingerprint": "fp2",
        "focused_monitor": 2,
    })
    assert eng.world.active_app == "Notepad"
    assert eng.world.active_monitor == 2
    print("OK window changed")


def test_load_for_command_blob():
    from neuron.v3.context_engine import reset_engine
    eng = reset_engine()
    eng.on_user_command("open chrome")
    eng.world.apply_observation({
        "active_application": "Chrome",
        "window": "YouTube",
        "url": "https://youtube.com",
        "focused_monitor": 1,
    })
    blob = eng.load_for_command()
    assert "WORLD_STATE" in blob
    assert "Chrome" in blob
    print("OK load_for_command")


def test_singleton_get_engine():
    from neuron.v3.context_engine import get_engine, reset_engine
    a = reset_engine()
    b = get_engine()
    assert a is b
    print("OK singleton")


if __name__ == "__main__":
    test_context_creation()
    test_verified_vs_attempted()
    test_failed_action_does_not_fake_success_app()
    test_recent_entity_tracking()
    test_task_lifecycle()
    test_session_reset()
    test_bounded_history()
    test_sensitive_filtering()
    test_window_changed_event()
    test_load_for_command_blob()
    test_singleton_get_engine()
    print("\nALL ContextEngine / WorldState tests passed")
