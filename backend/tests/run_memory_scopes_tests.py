"""Memory scope tests — Working / Session / Persistent."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_working_memory():
    from neuron.memory import scopes

    w = scopes.working()
    w.begin_task("open notepad")
    assert w.goal == "open notepad"
    assert w.status == "running"
    w.note_action("open_app", ok=True, detail="opened", args={"name": "Notepad"})
    w.note_observation("app=Notepad")
    blob = w.compact()
    assert "WORKING_MEMORY:" in blob
    assert "open notepad" in blob
    w.clear()
    assert w.goal == ""
    assert scopes.clear_working().startswith("Cleared working")
    print("OK working")


def test_session_memory():
    from neuron.memory import scopes

    s = scopes.session()
    s.clear()
    s.log("user", "open chrome")
    s.log("neuron", "Opening Chrome.")
    s.note_app("Chrome")
    s.note_site("youtube.com")
    s.note_monitor(1)
    blob = s.compact()
    assert "SESSION_MEMORY:" in blob
    assert "Chrome" in blob
    assert "youtube.com" in blob
    assert scopes.clear_session().startswith("Cleared session")
    assert not s.apps_used
    print("OK session")


def test_persistent_controls():
    from neuron.memory import scopes

    p = scopes.persistent()
    # Allowlisted user fact
    ok, msg = p.remember("favorite color", "blue")
    assert ok, msg
    assert p.recall("favorite color") == "blue"
    assert p.recall("user.favorite_color") == "blue"

    # Sensitive deny
    ok2, msg2 = p.remember("password", "hunter2")
    assert not ok2
    assert "denied" in msg2.lower() or "sensitive" in msg2.lower()

    # Prefixed allow
    ok3, msg3 = p.remember("pref.tts_rate", "1.1")
    assert ok3, msg3

    # Force bypass for system keys
    ok4, msg4 = p.remember("voice.wake_word", "required", force=True)
    assert ok4, msg4

    forgot_ok, forgot_msg = p.forget("favorite color")
    assert forgot_ok, forgot_msg
    assert p.recall("user.favorite_color") is None

    # clear requires confirm
    denied, dmsg = p.clear(confirm=False)
    assert not denied
    print("OK persistent", msg3[:40])


def test_memory_py_routes():
    import memory
    from neuron.memory import scopes

    scopes.session().clear()
    memory.log("user", "hello scopes")
    assert any(c.get("text") == "hello scopes" for c in scopes.session().conversation)

    msg = memory.remember("my nickname", "Jay")
    assert "Remembered" in msg or "remembered" in msg.lower()
    assert memory.recall("my nickname") == "Jay"
    assert memory.forget("my nickname").lower().startswith("forgot")

    blob = memory.context_blob("test")
    # After clear conversation may still show if we logged — session has hello
    assert isinstance(blob, str)
    print("OK memory.py bridge")


def test_context_scopes_order():
    from neuron.memory import scopes

    scopes.working().begin_task("click Search")
    scopes.working().note_action("click_element", ok=True, detail="clicked")
    scopes.session().clear()
    scopes.session().note_app("Chrome")
    scopes.session().log("user", "find search")
    blob = scopes.context_blob()
    assert "WORKING_MEMORY:" in blob
    assert "SESSION_MEMORY:" in blob
    # working appears before session
    assert blob.index("WORKING_MEMORY:") < blob.index("SESSION_MEMORY:")
    scopes.clear_working()
    scopes.clear_session()
    print("OK context order")


if __name__ == "__main__":
    test_working_memory()
    test_session_memory()
    test_persistent_controls()
    test_memory_py_routes()
    test_context_scopes_order()
    print("ALL memory scope tests passed")
