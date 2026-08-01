"""V3.8 — multi-monitor, multi-app, semantic adaptive skills."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fake_mons():
    return [
        {
            "id": 1,
            "left": 0,
            "top": 0,
            "width": 1920,
            "height": 1080,
            "primary": True,
            "work_left": 0,
            "work_top": 0,
            "work_width": 1920,
            "work_height": 1040,
            "roles": ["main", "primary", "left"],
            "label": "#1",
        },
        {
            "id": 2,
            "left": 1920,
            "top": 0,
            "width": 2560,
            "height": 1440,
            "primary": False,
            "work_left": 1920,
            "work_top": 0,
            "work_width": 2560,
            "work_height": 1400,
            "roles": ["secondary", "right", "other"],
            "label": "#2",
        },
    ]


def test_relative_monitor_refs():
    from neuron.windows import monitors as mon_mod

    mons = _fake_mons()
    assert mon_mod.resolve_monitor_ref("main", monitors=mons)["id"] == 1
    assert mon_mod.resolve_monitor_ref("monitor 2", monitors=mons)["id"] == 2
    assert mon_mod.resolve_monitor_ref("left", monitors=mons)["id"] == 1
    assert mon_mod.resolve_monitor_ref("right", monitors=mons)["id"] == 2
    assert mon_mod.resolve_monitor_ref("other", relative_to=1, monitors=mons)["id"] == 2
    assert mon_mod.resolve_monitor_ref("foreground", relative_to=2, monitors=mons)["id"] == 2
    # Never hardcode other → 2 at plan time
    assert mon_mod.normalize_monitor_arg("other") == "other"
    assert mon_mod.normalize_monitor_arg("foreground") == "foreground"
    print("OK relative monitor refs")


def test_multi_monitor_window_movement_mock():
    from neuron.windows import monitors as mon_mod

    moved = {}

    def fake_move(args):
        from neuron.windows.result import ok
        # Match production: "other" is relative to the window's current monitor.
        mon = mon_mod.resolve_monitor_ref(
            args.get("monitor"),
            relative_to=int(args.get("from_monitor") or 1),
            monitors=_fake_mons(),
        )
        moved["monitor"] = int(mon["id"])
        return ok(
            f"moved to {moved['monitor']}",
            state={"after_monitor": moved["monitor"], "before_monitor": 1},
            method="mock",
        )

    with mock.patch.object(mon_mod, "list_monitor_dicts", return_value=_fake_mons()), mock.patch.object(
        mon_mod, "move_window_to_monitor", side_effect=fake_move
    ):
        r = mon_mod.move_window_to_monitor({"name": "Chrome", "monitor": "other"})
    assert r.success
    assert moved["monitor"] == 2
    print("OK multi-monitor move mock")


def test_multi_app_workflow_compose():
    from neuron.v3.multi_app import compose_multi_app_plan, looks_multi_app

    text = (
        "Open Chrome on monitor 2, search YouTube for Blender animation tutorials, "
        "play the first result, and open Blender on monitor 1."
    )
    assert looks_multi_app(text)
    plan = compose_multi_app_plan(text)
    assert plan and len(plan["steps"]) >= 4
    actions = [s["action"] for s in plan["steps"]]
    assert "open_app" in actions
    assert "move_window_to_monitor" in actions
    assert "browser_search" in actions
    assert "play_result" in actions
    # Chrome → monitor 2, Blender → monitor 1
    moves = [
        s for s in plan["steps"] if s["action"] == "move_window_to_monitor"
    ]
    mons = {(s["args"]["name"], str(s["args"]["monitor"])) for s in moves}
    assert ("Chrome", "2") in mons
    assert ("Blender", "1") in mons
    # Every stage has expected_result for verify
    assert all(s.get("expected_result") for s in plan["steps"])
    print("OK multi-app compose", actions)


def test_capability_router_multi_app_and_other():
    from neuron.v3.capability_router import route
    from neuron.brain import tool_registry

    tool_registry.ensure_bootstrapped()
    text = (
        "Open Chrome on monitor 2, search YouTube for Blender animation tutorials, "
        "play the first result, and open Blender on monitor 1."
    )
    r = route(text)
    assert r.ok, r.reason
    assert r.capability and r.capability.id == "multi_app.workflow"
    assert len(r.steps) >= 4

    r2 = route("move chrome to the other monitor")
    assert r2.ok
    mon = (r2.steps[0].get("arguments") or r2.steps[0].get("args") or {}).get("monitor")
    assert mon == "other", f"must keep NL token, got {mon!r}"
    print("OK capability multi-app + other token")


def test_semantic_skill_creation_no_coords():
    from neuron.learning.procedures import save_procedure, clicks_to_steps
    from neuron.learning.semantic import sanitize_steps

    recipe = {
        "app": "notepad",
        "steps": [
            {"x": 50, "y": 60, "element": {"name": "File"}},
            {"x": 999, "y": 888, "element": {"name": ""}},
            {"screenshot": "blob", "pixels": [1, 2, 3], "element": {"name": "Edit"}},
        ],
    }
    steps = clicks_to_steps(recipe)
    assert all(s["action"] != "click" for s in steps)
    assert not any("screenshot" in s or "pixels" in (s.get("args") or {}) for s in steps)

    ok, msg, proc = save_procedure(
        skill_id="notepad.open_file_menu",
        steps=steps + [{"action": "click", "args": {"x": 1, "y": 2}}],
        say=["open file menu in notepad"],
        source="test",
    )
    assert ok, msg
    assert all(s["action"] != "click" for s in proc["steps"])
    assert proc.get("semantic") is True
    print("OK semantic skill creation", msg[:70])


def test_skill_execution_bind_params():
    from neuron.learning.semantic import bind_params
    from neuron.learning.procedures import get

    proc = get("blender.start_render")
    assert proc
    bound = bind_params(proc["steps"], {"project": "DemoAnim"})
    assert any(
        (s.get("args") or {}).get("query") == "DemoAnim"
        for s in bound
        if s.get("action") == "blender.open_project"
    )
    print("OK skill param bind")


def test_changed_window_positions_adaptive():
    """Semantic click_element by name does not embed absolute coords."""
    from neuron.learning.semantic import is_semantic_step, is_coordinate_step

    semantic = {
        "action": "click_element",
        "args": {"name": "Render"},
        "expected_result": "clicked Render",
    }
    coord = {"action": "click", "args": {"x": 400, "y": 300}}
    assert is_semantic_step(semantic)
    assert is_coordinate_step(coord)
    assert not is_semantic_step(coord)
    print("OK adaptive vs coordinate")


def test_missing_target_recovery_wrong_monitor():
    from neuron.brain import recover
    from neuron.brain.goal import GoalState
    from neuron.v3.loop_types import decide_recovery

    goal = GoalState(goal="place chrome")
    step = {"action": "type_text", "args": {"name": "Chrome", "text": "x", "monitor": "other"}}
    alts = recover.deterministic_recovery(
        step, "wrong monitor", goal, category="WRONG_MONITOR"
    )
    assert alts and alts[0]["action"] == "move_window_to_monitor"
    d = decide_recovery({"category": "WRONG_MONITOR"}, has_alternate=True)
    assert d.strategy == "alternate"
    print("OK missing/wrong monitor recovery")


def test_blender_start_render_skill_registered():
    from neuron.brain import tool_registry
    from neuron.skills import blender

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("blender.start_render")
    assert callable(blender.start_render)
    assert callable(blender.trigger_render)
    print("OK blender render skills registered")


def test_privacy_scrub_on_save():
    from neuron.learning.procedures import save_procedure

    ok, msg, _ = save_procedure(
        skill_id="web.enter_secret",
        steps=[{
            "action": "type_text",
            "args": {"text": "secret=abc123token", "name": "API Token"},
        }],
        say=["enter token"],
    )
    assert not ok
    print("OK privacy scrub", msg[:60])


if __name__ == "__main__":
    test_relative_monitor_refs()
    test_multi_monitor_window_movement_mock()
    test_multi_app_workflow_compose()
    test_capability_router_multi_app_and_other()
    test_semantic_skill_creation_no_coords()
    test_skill_execution_bind_params()
    test_changed_window_positions_adaptive()
    test_missing_target_recovery_wrong_monitor()
    test_blender_start_render_skill_registered()
    test_privacy_scrub_on_save()
    print("\nALL V3.8 multi-monitor / multi-app / skills tests passed")
