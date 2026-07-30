"""Phase 9 controlled procedure learning tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_skill_id():
    from neuron.learning.procedures import skill_id_from_goal
    assert skill_id_from_goal("create a new Blender project") == "blender.new_project"
    assert skill_id_from_goal("learn how I create a new Blender project") == "blender.new_project"
    print("OK skill id")


def test_refuse_source_rewrite():
    from neuron.learning.procedures import rejects_source_write, save_procedure
    assert rejects_source_write("edit backend/brain.py")
    assert rejects_source_write({"action": "create_file", "args": {"path": "backend/foo.py"}})
    ok, msg, _ = save_procedure(
        skill_id="neuron.patch_self",
        steps=[{"action": "create_file", "args": {"path": "backend/brain.py", "content": "x"}}],
        say=["rewrite yourself"],
    )
    assert not ok
    assert "source" in msg.lower() or "refusing" in msg.lower()
    print("OK refuse source")


def test_builtin_match_and_list():
    from neuron.learning.procedures import list_summary, match
    hit = match("create a blender project")
    assert hit and hit.get("id") == "blender.new_project"
    blob = list_summary()
    assert "blender.new_project" in blob
    print("OK builtin match")


def test_save_and_match_learned(tmp_path=None):
    from neuron.learning import procedures as proc

    ok, msg, p = proc.save_procedure(
        skill_id="notepad.type_hello",
        steps=[
            {"action": "open_app", "args": {"name": "notepad"}, "expected_result": "Notepad open"},
            {"action": "type_text", "args": {"text": "hello"}, "expected_result": "text typed"},
        ],
        say=["type hello in notepad", "notepad hello"],
        source="test",
    )
    assert ok, msg
    assert p and p["id"] == "notepad.type_hello"
    hit = proc.match("type hello in notepad")
    assert hit and hit["id"] == "notepad.type_hello"
    print("OK save/match", msg[:60])


def test_teach_parse_and_session():
    from neuron.learning import teach

    g = teach.parse_learn_goal("Neuron, learn how I create a new Blender project.")
    assert g and "blender" in g.lower()
    teach.cancel()
    msg = teach.start("create a new Blender project")
    assert teach.is_teaching()
    assert "blender.new_project" in msg
    # Finish without clicks → uses builtin seed for known skill
    out = teach.finish()
    assert "Learned skill" in out or "blender.new_project" in out or "steps" in out.lower()
    assert not teach.is_teaching()
    print("OK teach session", out[:80])


def test_clicks_to_steps():
    from neuron.learning.procedures import clicks_to_steps
    recipe = {
        "app": "blender",
        "steps": [
            {"button": "left", "x": 10, "y": 20, "element": {"name": "General"}},
            {"button": "left", "x": 30, "y": 40, "element": {"name": ""}},
        ],
    }
    steps = clicks_to_steps(recipe)
    assert steps[0]["action"] == "open_app"
    assert any(s.get("action") == "click_element" and s["args"].get("name") == "General" for s in steps)
    print("OK clicks_to_steps", len(steps))


def test_brain_learn_how_i():
    import brain
    from neuron.learning import teach
    teach.cancel()
    reply, acted = brain.handle_command("learn how I create a new Blender project")
    assert acted and teach.is_teaching(), (reply, teach.is_teaching())
    assert "teach me" in (reply or "").lower() or "blender.new_project" in (reply or "")
    reply2, acted2 = brain.handle_command("cancel teaching")
    assert acted2 and not teach.is_teaching()
    print("OK brain teach", (reply or "")[:60])


def test_registry_has_procedure():
    from neuron.brain import tool_registry
    tool_registry.reset_for_tests()
    import brain  # noqa
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("run_procedure")
    assert tool_registry.get("blender.new_project")
    print("OK registry procedure tools")


if __name__ == "__main__":
    test_skill_id()
    test_refuse_source_rewrite()
    test_builtin_match_and_list()
    test_save_and_match_learned()
    test_teach_parse_and_session()
    test_clicks_to_steps()
    test_brain_learn_how_i()
    test_registry_has_procedure()
    print("ALL Phase 9 learning tests passed")
