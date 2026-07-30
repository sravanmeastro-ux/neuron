"""Phase 9 OPAVR — GoalState, verify-hard, recover, structured trace."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_goal_state_progress():
    from neuron.brain.goal import GoalState

    g = GoalState.from_plan(
        "Open YouTube and play the first video",
        {
            "say": "On it.",
            "steps": [
                {"action": "browser_search", "args": {"site": "youtube", "query": "lofi"}},
                {"action": "browser_click", "args": {"index": 0}},
            ],
        },
        max_retries=3,
    )
    assert len(g.pending_steps) == 2
    g.complete_current(
        g.pending_steps[0],
        {"ok": True, "out": "Searched."},
        verify_note="url has youtube",
    )
    assert len(g.completed_steps) == 1
    assert len(g.pending_steps) == 1
    assert g.pending_steps[0]["action"] == "browser_click"
    blob = g.compact()
    assert "GOAL:" in blob and "PENDING:" in blob
    print("OK goal progress", g.compact().replace("\n", " | "))


def test_honest_failure_message():
    from neuron.brain.goal import GoalState

    g = GoalState(goal="Open Blender", max_retries=2)
    g.completed_steps = [{"action": "open_app"}]
    g.errors.append("Blender is not running and no window found")
    g.pending_steps = [{"action": "focus_app", "args": {"name": "Blender"}}]
    g.mark_failed()
    msg = g.honest_failure_message()
    assert "couldn't complete" in msg.lower() or "couldn" in msg.lower()
    assert "Blender" in msg
    assert "pretend" not in msg.lower()
    print("OK honest failure", msg[:100])


def test_verify_open_app_hard():
    from neuron.brain import verifier

    step = {"action": "open_app", "args": {"name": "Blender"}}
    with mock.patch("neuron.brain.verifier._check_app", return_value={
        "name": "Blender",
        "process_running": False,
        "window_exists": False,
        "window_title": "",
        "resolved": "Blender",
    }):
        ok, note = verifier.verify_step(step, "Opened Blender.", None, strict=True)
    assert not ok
    assert "not running" in note.lower() or "no window" in note.lower()

    with mock.patch("neuron.brain.verifier._check_app", return_value={
        "name": "Blender",
        "process_running": True,
        "window_exists": True,
        "window_title": "Blender",
        "resolved": "Blender",
    }):
        ok2, note2 = verifier.verify_step(step, "Opened Blender.", None, strict=True)
    assert ok2
    assert "verified" in note2.lower()
    print("OK hard verify open_app")


def test_deterministic_recover_open_app():
    from neuron.brain.goal import GoalState
    from neuron.brain import recover

    g = GoalState(goal="Open Blender")
    g.action_history.append({
        "action": "open_app",
        "args": {"name": "Blender"},
        "ok": False,
        "out": "fail",
    })
    alts = recover.deterministic_recovery(
        {"action": "open_app", "args": {"name": "Blender"}},
        "not running",
        g,
    )
    assert alts
    assert any(s["action"] == "focus_app" for s in alts)
    merged = recover.merge_recovery(
        {"action": "open_app", "args": {"name": "Blender"}},
        [{"action": "hotkey", "args": {"keys": "space"}}],
        alts,
    )
    assert merged[-1]["action"] == "hotkey"
    assert merged[0]["action"] in ("focus_app", "open_app")
    print("OK recover open_app", [s["action"] for s in merged])


def test_trace_phases():
    from neuron.brain.trace import Trace

    tr = Trace()
    tr.user("Open Blender")
    tr.context("scene=desktop")
    tr.plan({"say": "Opening.", "steps": [{"action": "open_app", "args": {"name": "Blender"}}]})
    tr.action({"action": "open_app", "args": {"name": "Blender"}})
    tr.result(True, "Opened Blender.")
    tr.verification(True, "verified process+window")
    tr.final("success", "Opened Blender.")
    phases = [e["phase"] for e in tr.to_list()]
    for need in ("USER", "CONTEXT", "PLAN", "ACTION", "RESULT", "VERIFICATION", "FINAL"):
        assert need in phases
    print("OK trace", phases)


def test_opavr_success_path():
    from neuron.brain import loop as opavr
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Opening Blender.",
        "steps": [{"action": "open_app", "args": {"name": "Blender"}}],
    }

    def fake_exec(p, confirmed=False, timeout=None):
        er = ExecutionResult()
        er.outcomes = ["Opened Blender."]
        er.steps_run = [{
            "action": "open_app",
            "args": {"name": "Blender"},
            "ok": True,
            "out": "Opened Blender.",
            "ms": 10,
            "result": {"success": True, "state": {"verified": True}},
        }]
        return er

    with mock.patch("neuron.brain.loop.executor.execute_plan", side_effect=fake_exec), mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step",
        return_value=VerifyResult(True, "verified Blender window"),
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world",
        return_value={"app": "Blender", "window": "Blender"},
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_goal",
        return_value=VerifyResult(True, "final goal verified"),
    ):
        say, acted, meta, goal = opavr.run_opavr(
            request="Open Blender",
            plan=plan,
            context="",
        )
    assert acted
    assert goal.status == "success"
    assert len(goal.completed_steps) == 1
    assert "Blender" in (say or "")
    # Closed-loop enrichment
    step0 = goal.completed_steps[0]
    assert step0.get("expected_result")
    assert step0.get("target") == "Blender" or (step0.get("args") or {}).get("name") == "Blender"
    print("OK opavr success", say)


def test_opavr_verify_fail_then_recover():
    from neuron.brain import loop as opavr
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Opening.",
        "steps": [{"action": "open_app", "args": {"name": "Blender"}}],
    }
    calls = {"n": 0}

    def fake_exec(p, confirmed=False, timeout=None):
        calls["n"] += 1
        er = ExecutionResult()
        step = (p.get("steps") or [{}])[0]
        action = step.get("action")
        er.outcomes = [f"ran {action}"]
        er.steps_run = [{
            "action": action,
            "args": step.get("args") or {},
            "ok": True,
            "out": f"ran {action}",
            "ms": 5,
        }]
        return er

    verify_calls = {"n": 0}

    def fake_verify(step, entry, strict=True):
        verify_calls["n"] += 1
        # First open_app fails verify; focus_app (recovery) succeeds
        if step.get("action") == "open_app":
            return VerifyResult(False, "Blender is not running and no window found")
        return VerifyResult(True, "verified via focus")

    with mock.patch("neuron.brain.loop.executor.execute_plan", side_effect=fake_exec), mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step", side_effect=fake_verify
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world", return_value={}
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_goal",
        return_value=VerifyResult(True, "final goal verified"),
    ), mock.patch(
        "neuron.brain.loop.verifier.diagnose_failure",
        return_value={"cause": "app_not_present", "detail": "not running"},
    ), mock.patch(
        "neuron.brain.recover.llm_replan_pending", return_value=None
    ):
        say, acted, meta, goal = opavr.run_opavr(
            request="Open Blender",
            plan=plan,
            context="",
        )
    assert meta.get("recovered") or goal.status in ("success", "failed")
    # Should have tried focus_app recovery after open failed verify
    assert calls["n"] >= 2
    assert goal.status == "success"
    print("OK opavr recover", meta.get("recovered"), goal.status, say)


def test_opavr_multi_step_no_full_restart():
    from neuron.brain import loop as opavr
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Playing.",
        "steps": [
            {"action": "browser_search", "args": {"site": "youtube", "query": "x"}},
            {"action": "browser_click", "args": {"index": 0}},
        ],
    }
    executed = []

    def fake_exec(p, confirmed=False, timeout=None):
        step = (p.get("steps") or [{}])[0]
        executed.append(step.get("action"))
        er = ExecutionResult()
        # First click attempt fails; recovery click succeeds
        if step.get("action") == "browser_click" and executed.count("browser_click") == 1:
            er.errors = ["click missed"]
            er.failed_step = step
            er.steps_run = [{
                "action": "browser_click",
                "args": step.get("args") or {},
                "ok": False,
                "out": "click missed",
            }]
        else:
            er.outcomes = [f"ok {step.get('action')}"]
            er.steps_run = [{
                "action": step.get("action"),
                "args": step.get("args") or {},
                "ok": True,
                "out": f"ok {step.get('action')}",
            }]
        return er

    def fake_verify(step, entry, strict=True):
        if entry.get("ok") is False:
            return VerifyResult(False, entry.get("out") or "fail")
        return VerifyResult(True, "ok")

    replan_calls = []

    def fake_llm_replan(request, context, goal, failed_step, error, normalized=""):
        replan_calls.append(list(goal.completed_steps))
        # Remaining work only — click again with name
        return {
            "say": "Retrying click.",
            "steps": [{"action": "browser_click", "args": {"index": 0, "name": "first"}}],
        }

    with mock.patch("neuron.brain.loop.executor.execute_plan", side_effect=fake_exec), mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step", side_effect=fake_verify
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world", return_value={"url": "https://youtube.com"}
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_goal",
        return_value=VerifyResult(True, "final goal verified"),
    ), mock.patch(
        "neuron.brain.loop.verifier.diagnose_failure",
        return_value={"cause": "target_not_found", "detail": "click missed"},
    ), mock.patch(
        "neuron.brain.recover.deterministic_recovery", return_value=None
    ), mock.patch(
        "neuron.brain.recover.llm_replan_pending", side_effect=fake_llm_replan
    ):
        say, acted, meta, goal = opavr.run_opavr(
            request="Open YouTube and play the first video",
            plan=plan,
            context="",
        )
    assert acted
    assert "browser_search" in executed
    # Search should not be repeated after replan
    assert executed.count("browser_search") == 1
    assert replan_calls and len(replan_calls[0]) >= 1
    assert replan_calls[0][0].get("action") == "browser_search"
    assert meta.get("replanned")
    assert goal.status == "success"
    print("OK multi-step replan from state", executed)


def test_step_enrichment():
    from neuron.brain.normalize import normalize_plan
    from neuron.brain.step import Step, infer_expected_result

    plan = normalize_plan({
        "say": "Opening.",
        "steps": [{"tool": "open_app", "arguments": {"application": "Blender"}}],
    })
    step = plan["steps"][0]
    assert step["action"] == "open_app"
    assert step["args"]["name"] == "Blender"
    assert step["target"] == "Blender"
    assert "Blender" in step["expected_result"]
    assert step["timeout"] > 0
    assert step["retry_limit"] >= 0

    s = Step.from_dict({
        "action": "browser_open",
        "args": {"site": "youtube.com"},
        "expected_result": "browser URL reflects youtube",
        "timeout": 30,
        "retry_limit": 1,
    })
    assert s is not None
    assert s.target == "youtube.com"
    assert s.timeout == 30.0
    assert "running" in infer_expected_result("open_app", {"name": "X"}, "X")
    print("OK step enrichment", step)


def test_agent_loop_facade():
    from neuron.brain.agent_loop import AgentLoop
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.goal import GoalState
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Opening.",
        "steps": [{"action": "open_app", "args": {"name": "Notepad"}}],
    }

    def fake_exec(p, confirmed=False, timeout=None):
        er = ExecutionResult()
        er.outcomes = ["Opened Notepad."]
        er.steps_run = [{
            "action": "open_app",
            "args": {"name": "Notepad"},
            "ok": True,
            "out": "Opened Notepad.",
            "ms": 5,
        }]
        return er

    with mock.patch("neuron.brain.loop.executor.execute_plan", side_effect=fake_exec), mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step",
        return_value=VerifyResult(True, "verified"),
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world",
        return_value={"app": "Notepad"},
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_goal",
        return_value=VerifyResult(True, "final goal verified"),
    ):
        loop = AgentLoop()
        say, acted, meta, goal = loop.run("open notepad", plan=plan)
    assert acted and goal.status == "success"
    assert isinstance(goal, GoalState)
    assert meta.get("trace")
    print("OK AgentLoop facade", say)


def test_agent_wires_trace():
    from neuron.brain import agent
    from neuron.brain.goal import GoalState

    g = GoalState(goal="open notepad", status="success")
    g.completed_steps = [{"action": "open_app"}]
    fake_meta = {
        "path": "opavr",
        "replanned": False,
        "recovered": False,
        "steps": [{"action": "open_app", "ok": True}],
        "needs_confirm": None,
        "diagnoses": [],
    }
    with mock.patch(
        "neuron.brain.agent.AgentLoop.run",
        return_value=("Opened Notepad.", True, fake_meta, g),
    ):
        say, acted, meta = agent.run("open notepad", use_rules_fallback=False)
    assert acted
    assert say
    assert meta.get("agent_loop") is True
    assert "trace" in meta
    assert meta.get("goal", {}).get("status") == "success"
    print("OK agent AgentLoop meta", meta.get("path"), meta.get("agent_loop"))


def test_screen_verify_helpers():
    from neuron.brain import verifier

    assert verifier.needs_screen_verify({
        "action": "click_ui_element",
        "args": {"name": "Save"},
    })
    assert verifier.needs_screen_verify({
        "action": "open_app",
        "args": {"name": "Blender"},
        "expected_result": "button 'Render' is visible on screen",
    })
    assert not verifier.needs_screen_verify({
        "action": "open_app",
        "args": {"name": "Blender"},
        "expected_result": "app 'Blender' is running or has a visible window",
    })
    assert verifier.needs_ocr_verify({
        "action": "type_text",
        "args": {"text": "hello"},
    })

    # Text match against screen blob without calling real OCR
    vr = verifier._match_expected_result(
        "button 'Save' is visible on screen",
        {"screen_blob": "File | Edit | Save | Cancel", "screen_sources": ["uia"]},
        "clicked",
    )
    assert vr.ok
    vr2 = verifier._match_expected_result(
        "button 'Export' is visible on screen",
        {"screen_blob": "File | Edit | Save | Cancel", "screen_sources": ["uia"]},
        "clicked",
    )
    assert not vr2.ok

    # UI find verify uses screen_blob
    ok, note = verifier.verify_step(
        {"action": "find_ui_element", "args": {"name": "Save"}},
        "found Save",
        None,
        strict=True,
        world={"screen_blob": "File | Save | Help"},
    )
    assert ok
    ok2, note2 = verifier.verify_step(
        {"action": "find_ui_element", "args": {"name": "Export"}},
        "found Export",
        None,
        strict=True,
        world={"screen_blob": "File | Save | Help"},
    )
    assert not ok2
    print("OK screen verify helpers", note, note2)


if __name__ == "__main__":
    test_goal_state_progress()
    test_honest_failure_message()
    test_verify_open_app_hard()
    test_deterministic_recover_open_app()
    test_trace_phases()
    test_step_enrichment()
    test_screen_verify_helpers()
    test_opavr_success_path()
    test_opavr_verify_fail_then_recover()
    test_opavr_multi_step_no_full_restart()
    test_agent_loop_facade()
    test_agent_wires_trace()
    print("\nPhase 9 OPAVR tests passed.")
