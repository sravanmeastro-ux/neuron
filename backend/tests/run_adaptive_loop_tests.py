"""V3.7 adaptive AgentLoop — failure injection + diagnosis/recovery tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_failure_categories_present():
    from neuron.v3.loop_types import FAILURE_CATEGORIES

    needed = {
        "ELEMENT_NOT_FOUND",
        "WINDOW_NOT_FOUND",
        "APP_NOT_RUNNING",
        "PAGE_NOT_LOADED",
        "POPUP_DETECTED",
        "FOCUS_LOST",
        "WRONG_WINDOW",
        "WRONG_MONITOR",
        "ACTION_TIMEOUT",
        "VERIFICATION_FAILED",
        "PERMISSION_REQUIRED",
        "AMBIGUOUS_TARGET",
        "POLICY_BLOCKED",
        "INTERRUPTED",
    }
    assert needed.issubset(set(FAILURE_CATEGORIES))
    print("OK categories", len(FAILURE_CATEGORIES))


def test_diagnose_all_categories():
    """Every structured failure category must classify from representative errors."""
    from neuron.brain import verifier

    cases = [
        ({"action": "click_element", "args": {"name": "Export"}}, "click missed", {}, "ELEMENT_NOT_FOUND"),
        ({"action": "focus_app", "args": {"name": "Slack"}}, "window not found", {}, "WINDOW_NOT_FOUND"),
        ({"action": "open_app", "args": {"name": "Blender"}}, "Blender is not running and no window found", {}, "APP_NOT_RUNNING"),
        ({"action": "browser_navigate", "args": {"url": "x"}}, "page not loaded / blank", {}, "PAGE_NOT_LOADED"),
        ({}, "cookie consent popup blocking", {}, "POPUP_DETECTED"),
        ({}, "focus lost on target window", {}, "FOCUS_LOST"),
        ({"action": "type_text", "args": {"name": "Notepad"}}, "wrong window is foreground", {"app": "Chrome", "window": "Google"}, "WRONG_WINDOW"),
        ({}, "wrong monitor: expected 2 not on monitor 1", {}, "WRONG_MONITOR"),
        ({}, "Tool timed out after 45s", {}, "ACTION_TIMEOUT"),
        ({"action": "click_element", "args": {"name": "Ok"}}, "verification failed after click", {"app": "App", "window": "App"}, "VERIFICATION_FAILED"),
        ({}, "Confirmation required", {}, "PERMISSION_REQUIRED"),
        ({}, "Which one did you mean?", {}, "AMBIGUOUS_TARGET"),
        ({}, "policy blocked by safety", {}, "POLICY_BLOCKED"),
        ({}, "interrupted by user", {}, "INTERRUPTED"),
    ]
    for step, err, world, want in cases:
        d = verifier.diagnose_failure(step, err, world)
        assert d["category"] == want, f"{err!r} → {d['category']} want {want}"
    # Bare "blocked" must NOT become POLICY (popup / UI blocking phrases)
    d_pop = verifier.diagnose_failure({}, "popup blocked the click", {})
    assert d_pop["category"] == "POPUP_DETECTED"
    print("OK diagnose all categories")


def test_decide_recovery_all_categories():
    from neuron.v3.loop_types import decide_recovery

    expect = {
        "POLICY_BLOCKED": ("blocked", "BLOCKED"),
        "PERMISSION_REQUIRED": ("ask_user", "NEEDS_USER"),
        "AMBIGUOUS_TARGET": ("ask_user", "NEEDS_USER"),
        "INTERRUPTED": ("fail", "INTERRUPTED"),
        "ACTION_TIMEOUT": ("retry", "RETRY"),  # no alternate
        "PAGE_NOT_LOADED": ("retry", "RETRY"),
        "POPUP_DETECTED": ("retry", "RETRY"),
        "FOCUS_LOST": ("retry", "RETRY"),
        "VERIFICATION_FAILED": ("retry", "RETRY"),
        "APP_NOT_RUNNING": ("replan", "NEEDS_REPLAN"),  # no alternate, has global budget
        "ELEMENT_NOT_FOUND": ("replan", "NEEDS_REPLAN"),
        "WINDOW_NOT_FOUND": ("replan", "NEEDS_REPLAN"),
        "WRONG_WINDOW": ("replan", "NEEDS_REPLAN"),
        "WRONG_MONITOR": ("retry", "RETRY"),
    }
    for cat, (strat, status) in expect.items():
        d = decide_recovery(
            {"category": cat},
            has_alternate=False,
            step_retries=0,
            max_step_retries=2,
            global_retries=0,
            max_global_retries=3,
        )
        assert d.strategy == strat, f"{cat}: strategy {d.strategy} want {strat}"
        assert d.status == status, f"{cat}: status {d.status} want {status}"

    # With alternate available → alternate for structural misses
    for cat in (
        "ELEMENT_NOT_FOUND",
        "WINDOW_NOT_FOUND",
        "APP_NOT_RUNNING",
        "POPUP_DETECTED",
        "WRONG_MONITOR",
        "FOCUS_LOST",
        "WRONG_WINDOW",
        "ACTION_TIMEOUT",
        "PAGE_NOT_LOADED",
        "VERIFICATION_FAILED",
    ):
        d = decide_recovery({"category": cat}, has_alternate=True, step_retries=0)
        assert d.strategy == "alternate", f"{cat} with alt → {d.strategy}"
    print("OK decide_recovery all categories")


def test_category_aware_recovery_steps():
    from neuron.brain import recover
    from neuron.brain.goal import GoalState

    goal = GoalState(goal="test")
    step = {"action": "click_element", "args": {"name": "Export"}}

    cases = [
        ("POPUP_DETECTED", "press_keys"),
        ("FOCUS_LOST", "focus_app"),
        ("WRONG_WINDOW", "focus_app"),
        ("WRONG_MONITOR", "move_window_to_monitor"),
        ("ACTION_TIMEOUT", "wait"),
        ("PAGE_NOT_LOADED", "wait"),
        ("WINDOW_NOT_FOUND", "focus_app"),
        ("APP_NOT_RUNNING", "focus_app"),
        ("VERIFICATION_FAILED", "wait"),
        ("POLICY_BLOCKED", None),
        ("PERMISSION_REQUIRED", None),
        ("AMBIGUOUS_TARGET", None),
        ("INTERRUPTED", None),
    ]
    for cat, first_action in cases:
        s = dict(step)
        if cat in ("FOCUS_LOST", "WRONG_WINDOW", "WRONG_MONITOR", "WINDOW_NOT_FOUND", "APP_NOT_RUNNING"):
            s = {"action": "type_text", "args": {"name": "Notepad", "text": "x", "monitor": 2}}
        alts = recover.deterministic_recovery(s, f"err for {cat}", goal, category=cat)
        if first_action is None:
            assert alts is None, f"{cat} should have no recovery steps"
        else:
            assert alts and alts[0].get("action") == first_action, f"{cat} → {alts}"

    # ELEMENT_NOT_FOUND → action alternate find_element
    alts = recover.deterministic_recovery(
        {"action": "click_element", "args": {"name": "Export"}},
        "not found",
        goal,
        category="ELEMENT_NOT_FOUND",
    )
    assert alts and alts[0]["action"] == "find_element"
    print("OK category-aware recovery steps")


def test_diagnose_app_not_running():
    from neuron.brain import verifier

    d = verifier.diagnose_failure(
        {"action": "open_app", "args": {"name": "Blender"}},
        "Blender is not running and no window found",
        {"app": "Chrome", "window": "Google"},
    )
    assert d["category"] == "APP_NOT_RUNNING"
    assert d["cause"] == "app_not_present"
    print("OK diagnose APP_NOT_RUNNING")


def test_diagnose_element_not_found():
    from neuron.brain import verifier

    d = verifier.diagnose_failure(
        {"action": "click_element", "args": {"name": "Export"}},
        "click missed",
        {},
    )
    assert d["category"] == "ELEMENT_NOT_FOUND"
    print("OK diagnose ELEMENT_NOT_FOUND")


def test_diagnose_timeout_popup_permission():
    from neuron.brain import verifier

    assert verifier.diagnose_failure({}, "Tool timed out after 45s", {})["category"] == "ACTION_TIMEOUT"
    assert verifier.diagnose_failure({}, "cookie consent popup blocking", {})["category"] == "POPUP_DETECTED"
    assert verifier.diagnose_failure({}, "Confirmation required", {})["category"] == "PERMISSION_REQUIRED"
    assert verifier.diagnose_failure({}, "Which one did you mean?", {})["category"] == "AMBIGUOUS_TARGET"
    print("OK diagnose timeout/popup/permission/ambiguous")


def test_decide_recovery_strategies():
    from neuron.v3.loop_types import decide_recovery

    d = decide_recovery(
        {"category": "APP_NOT_RUNNING", "detail": "missing"},
        has_alternate=True,
        step_retries=0,
        max_step_retries=2,
    )
    assert d.strategy == "alternate"
    assert d.status == "RETRY"

    d2 = decide_recovery(
        {"category": "PERMISSION_REQUIRED"},
        has_alternate=False,
    )
    assert d2.strategy == "ask_user"
    assert d2.status == "NEEDS_USER"

    d3 = decide_recovery(
        {"category": "POLICY_BLOCKED"},
    )
    assert d3.strategy == "blocked"
    assert d3.status == "BLOCKED"

    d4 = decide_recovery(
        {"category": "ACTION_TIMEOUT"},
        has_alternate=False,
        step_retries=0,
        max_step_retries=2,
    )
    assert d4.strategy == "retry"
    print("OK decide_recovery", d.strategy, d2.strategy, d3.strategy, d4.strategy)


def test_inject_app_not_running_recovers():
    """Failure injection: open_app verifies false → alternate focus_app succeeds."""
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
        step = (p.get("steps") or [{}])[0]
        er = ExecutionResult()
        er.outcomes = [f"ran {step.get('action')}"]
        er.steps_run = [{
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": True,
            "out": f"ran {step.get('action')}",
            "ms": 5,
        }]
        return er

    verify_n = {"n": 0}

    def fake_verify(step, entry, strict=True):
        verify_n["n"] += 1
        act = step.get("action")
        if act == "open_app":
            return VerifyResult(False, "Blender is not running and no window found")
        return VerifyResult(True, "verified via focus")

    with mock.patch.object(opavr.executor, "execute_plan", side_effect=fake_exec), mock.patch.object(
        opavr.verifier, "verify_execution_step", side_effect=fake_verify
    ), mock.patch.object(
        opavr.verifier, "observe_world", return_value={"app": "", "window": ""}
    ), mock.patch.object(
        opavr.verifier, "verify_goal", return_value=VerifyResult(True, "final goal verified")
    ), mock.patch.object(opavr.planner, "plan", return_value=plan):
        say, acted, meta, goal = opavr.run_opavr(
            request="Open Blender",
            plan=plan,
        )
    assert acted
    assert meta.get("recovered") or goal.status == "success"
    assert any(
        (d.get("category") == "APP_NOT_RUNNING" or d.get("cause") == "app_not_present")
        for d in (meta.get("diagnoses") or [])
    )
    assert goal.status == "success"
    print("OK inject APP_NOT_RUNNING recover", meta.get("loop_status"), say)


def test_inject_element_not_found_alternate():
    from neuron.brain import loop as opavr
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Clicking.",
        "steps": [{"action": "click_element", "args": {"name": "Export"}}],
    }
    executed = []

    def fake_exec(p, confirmed=False, timeout=None):
        step = (p.get("steps") or [{}])[0]
        executed.append(step.get("action"))
        er = ExecutionResult()
        if step.get("action") == "click_element" and executed.count("click_element") == 1:
            er.errors = ["click missed"]
            er.failed_step = step
            er.steps_run = [{
                "action": "click_element",
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
        if not entry.get("ok"):
            return VerifyResult(False, entry.get("out") or "fail")
        return VerifyResult(True, "ok")

    with mock.patch.object(opavr.executor, "execute_plan", side_effect=fake_exec), mock.patch.object(
        opavr.verifier, "verify_execution_step", side_effect=fake_verify
    ), mock.patch.object(
        opavr.verifier, "observe_world", return_value={"app": "Blender"}
    ), mock.patch.object(
        opavr.verifier, "verify_goal", return_value=VerifyResult(True, "final ok")
    ):
        say, acted, meta, goal = opavr.run_opavr(request="click Export", plan=plan)

    assert any(d.get("category") == "ELEMENT_NOT_FOUND" for d in (meta.get("diagnoses") or []))
    assert "find_element" in executed or meta.get("recovered")
    print("OK inject ELEMENT_NOT_FOUND", executed, goal.status)


def test_inject_popup_recovers_with_esc():
    from neuron.brain import loop as opavr
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Click.",
        "steps": [{"action": "click_element", "args": {"name": "Save"}}],
    }
    executed = []

    def fake_exec(p, confirmed=False, timeout=None):
        step = (p.get("steps") or [{}])[0]
        executed.append(step.get("action"))
        er = ExecutionResult()
        er.outcomes = [f"ok {step.get('action')}"]
        er.steps_run = [{
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": True,
            "out": f"ok {step.get('action')}",
        }]
        return er

    verify_n = {"n": 0}

    def fake_verify(step, entry, strict=True):
        verify_n["n"] += 1
        if step.get("action") == "click_element" and verify_n["n"] == 1:
            return VerifyResult(False, "cookie consent popup blocking")
        return VerifyResult(True, "ok")

    with mock.patch.object(opavr.executor, "execute_plan", side_effect=fake_exec), mock.patch.object(
        opavr.verifier, "verify_execution_step", side_effect=fake_verify
    ), mock.patch.object(
        opavr.verifier, "observe_world", return_value={"app": "Chrome"}
    ), mock.patch.object(
        opavr.verifier, "verify_goal", return_value=VerifyResult(True, "ok")
    ):
        say, acted, meta, goal = opavr.run_opavr(request="click Save", plan=plan)

    assert any(d.get("category") == "POPUP_DETECTED" for d in (meta.get("diagnoses") or []))
    assert "press_keys" in executed
    assert goal.status == "success"
    print("OK inject POPUP_DETECTED", executed)


def test_inject_interrupt_stops():
    from neuron.brain import loop as opavr
    from neuron.speech import interrupt as interrupt_mod
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "Working.",
        "steps": [
            {"action": "open_app", "args": {"name": "Notepad"}},
            {"action": "type_text", "args": {"text": "hi"}},
        ],
    }
    interrupt_mod.clear()
    interrupt_mod.request(reason="test")

    with mock.patch.object(
        opavr.verifier, "observe_world", return_value={}
    ), mock.patch.object(
        opavr.verifier, "verify_goal", return_value=VerifyResult(True, "ok")
    ):
        say, acted, meta, goal = opavr.run_opavr(request="open notepad", plan=plan)
    interrupt_mod.clear()
    assert meta.get("interrupted") or meta.get("loop_status") == "INTERRUPTED"
    assert say == "Stopped."
    print("OK interrupt stops", meta.get("loop_status"))


def test_neuron_cancel_phrase():
    from neuron.speech.interrupt import is_stop_phrase

    assert is_stop_phrase("Neuron stop")
    assert is_stop_phrase("Neuron cancel")
    assert is_stop_phrase("cancel neuron")
    assert is_stop_phrase("cancel that")
    assert not is_stop_phrase("stop the video")
    print("OK stop/cancel phrases")


def test_blender_success_requires_detection():
    """Opening Blender succeeds only when detected — not mere attempt."""
    from neuron.brain import verifier

    step = {"action": "open_app", "args": {"name": "Blender"}}
    with mock.patch.object(
        verifier, "_check_app", return_value={"process_running": False, "window_exists": False, "resolved": "Blender"}
    ):
        vr = verifier.verify_step_detailed(step, "launched", None, strict=True)
    assert not vr.ok
    assert "not running" in vr.note.lower() or "no window" in vr.note.lower()

    with mock.patch.object(
        verifier,
        "_check_app",
        return_value={
            "process_running": True,
            "window_exists": True,
            "resolved": "Blender",
            "window_title": "Blender",
        },
    ):
        vr2 = verifier.verify_step_detailed(step, "launched", None, strict=True)
    assert vr2.ok
    print("OK Blender verify requires detection")


def test_safety_not_weakened_blocked():
    from neuron.brain import loop as opavr

    plan = {
        "say": "evil",
        "steps": [{"action": "run_shell", "arguments": {"command": "rm -rf /"}}],
    }
    # plan validator may reject first; also safety check
    say, acted, meta, goal = opavr.run_opavr(request="wipe disk", plan=plan)
    assert meta.get("path") in ("plan_rejected", "blocked", "needs_confirm") or goal.status in (
        "failed", "blocked", "needs_confirm"
    )
    assert goal.status != "success"
    print("OK safety not weakened", meta.get("path"), goal.status)


def test_bounded_no_infinite_loop():
    from neuron.brain import loop as opavr
    from neuron.brain.executor import ExecutionResult
    from neuron.brain.verifier import VerifyResult

    plan = {
        "say": "x",
        "steps": [{"action": "open_app", "args": {"name": "MissingAppXYZ"}}],
    }
    n = {"exec": 0}

    def always_fail_exec(p, confirmed=False, timeout=None):
        n["exec"] += 1
        step = (p.get("steps") or [{}])[0]
        er = ExecutionResult()
        er.outcomes = ["attempted"]
        er.steps_run = [{
            "action": step.get("action"),
            "args": step.get("args") or {},
            "ok": True,
            "out": "attempted",
        }]
        return er

    with mock.patch.object(opavr.executor, "execute_plan", side_effect=always_fail_exec), mock.patch.object(
        opavr.verifier,
        "verify_execution_step",
        return_value=VerifyResult(False, "MissingAppXYZ is not running and no window found"),
    ), mock.patch.object(
        opavr.verifier, "observe_world", return_value={}
    ), mock.patch.object(
        opavr.recover, "llm_replan_pending", return_value={"say": "give up", "steps": []}
    ):
        say, acted, meta, goal = opavr.run_opavr(request="open MissingAppXYZ", plan=plan)

    assert n["exec"] <= 20  # bounded
    assert goal.status in ("failed", "partial_success")
    assert meta.get("loop_status") in ("FAILED", "PARTIAL_SUCCESS", "NEEDS_REPLAN")
    print("OK bounded retries", n["exec"], goal.status)


if __name__ == "__main__":
    test_failure_categories_present()
    test_diagnose_all_categories()
    test_decide_recovery_all_categories()
    test_category_aware_recovery_steps()
    test_diagnose_app_not_running()
    test_diagnose_element_not_found()
    test_diagnose_timeout_popup_permission()
    test_decide_recovery_strategies()
    test_inject_app_not_running_recovers()
    test_inject_element_not_found_alternate()
    test_inject_popup_recovers_with_esc()
    test_inject_interrupt_stops()
    test_neuron_cancel_phrase()
    test_blender_success_requires_detection()
    test_safety_not_weakened_blocked()
    test_bounded_no_infinite_loop()
    print("\nALL V3.7 adaptive AgentLoop tests passed")
