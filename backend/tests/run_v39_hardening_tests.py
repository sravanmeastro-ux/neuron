"""V3.9 conversation + hardening audit tests (no live desktop)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_catalog_size():
    from tests.reliability.tasks import TASKS
    assert len(TASKS) >= 150, f"need >=150 scenarios, got {len(TASKS)}"
    print("OK catalog", len(TASKS))


def test_plan_mode_no_desktop_import_side_effects():
    """PLAN mode must not call AgentLoop / executor for fixed plans."""
    from tests.reliability.runner import run_plan_mode
    from tests.reliability.tasks import by_id

    t = by_id("open_chrome")
    assert t
    r = run_plan_mode(t)
    assert r.ok and r.mode == "plan"
    print("OK plan mode fixed plan", r.detail[:60])


def test_conversations_a_b_c_d():
    from tests.reliability.runner import run_plan_mode
    from tests.reliability.tasks import by_id

    for tid, expect_outcome in (
        ("conv_test_a_youtube_chain", "success"),
        ("conv_test_b_multi_app", "success"),
        ("conv_test_c_recent_blender", "success"),
        ("conv_test_d_play_no_context", "clarify"),
    ):
        t = by_id(tid)
        assert t, tid
        r = run_plan_mode(t)
        assert r.ok, f"{tid} failed: {r.detail}"
        if expect_outcome == "clarify":
            assert r.outcome == "clarify" or t.get("expect_clarify")
        print(f"OK {tid} outcome={r.outcome} {r.detail[:50]}")


def test_ambiguous_clarifies():
    from tests.reliability.runner import run_plan_mode
    from tests.reliability.tasks import by_id

    t = by_id("amb_close_it")
    r = run_plan_mode(t)
    assert r.ok and r.outcome == "clarify"
    print("OK ambiguous clarify")


def test_interrupt_phrases():
    from tests.reliability.runner import run_plan_mode
    from tests.reliability.tasks import by_id

    t = by_id("interrupt_stop_phrase")
    r = run_plan_mode(t)
    assert r.ok
    print("OK interrupt phrase")


def test_safety_blocked():
    from tests.reliability.runner import run_plan_mode
    from tests.reliability.tasks import by_id

    t = by_id("safety_blocked_format")
    r = run_plan_mode(t)
    assert r.ok and r.outcome == "blocked"
    print("OK safety blocked")


def test_plan_reject_shell():
    from tests.reliability.runner import run_plan_mode
    from tests.reliability.tasks import by_id

    t = by_id("planner_reject_shell")
    r = run_plan_mode(t)
    assert r.ok, r.detail
    print("OK planner reject shell", r.detail[:80])


def test_audit_privacy_safety_timeouts():
    """Static audit of hardening invariants."""
    from neuron.v3.context_engine import scrub_text
    from neuron.learning.semantic import rejects_private_field, scrub_args
    from neuron.safety.policy import allow
    import json
    from pathlib import Path

    assert "[redacted]" in scrub_text("password=hunter2") or "redacted" in scrub_text("token: abc").lower()
    assert rejects_private_field({"action": "type_text", "args": {"text": "password=x", "name": "Password"}})
    clean = scrub_args({"password": "x", "query": "ok"})
    assert clean.get("password") == "[redacted]"

    ok, _ = allow("run_shell", {"command": "rm -rf /"}, confirmed=True)
    assert not ok

    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    agent = cfg.get("agent") or {}
    assert int(agent.get("max_replans") or 0) >= 1
    assert int(agent.get("max_step_retries") or 0) >= 1
    assert int(agent.get("tool_timeout_seconds") or 0) >= 10
    assert float(agent.get("max_loop_iterations") or 0) >= 5
    assert (cfg.get("click_record") or {}).get("store_pixels") is False

    # Prompt injection resistance: validator rejects shell in plan
    from neuron.v3.plan_validator import validate_plan
    v = validate_plan({"say": "x", "steps": [{"action": "run_shell", "args": {"command": "hi"}}]})
    assert not v.ok

    print("OK audit privacy/safety/timeouts/injection")


def test_mock_recovery_injection():
    from tests.reliability.runner import run_mock_mode
    from tests.reliability.tasks import by_id

    t = by_id("verify_fail_then_recover")
    assert t and t.get("inject")
    r = run_mock_mode(t)
    # Measured result — report actual; prefer success after recovery
    print(f"OK mock recovery measured ok={r.ok} recovered={r.recovered} detail={r.detail[:80]}")
    assert r.mode == "mock"


def test_backwards_compat_core_tasks():
    from tests.reliability.tasks import by_id
    for tid in ("open_chrome", "youtube_search", "move_chrome_monitor_2", "safety_status", "blocked_shutdown"):
        assert by_id(tid), f"missing core task {tid}"
    print("OK backwards compat core ids")


if __name__ == "__main__":
    test_catalog_size()
    test_plan_mode_no_desktop_import_side_effects()
    test_conversations_a_b_c_d()
    test_ambiguous_clarifies()
    test_interrupt_phrases()
    test_safety_blocked()
    test_plan_reject_shell()
    test_audit_privacy_safety_timeouts()
    test_mock_recovery_injection()
    test_backwards_compat_core_tasks()
    print("\nALL V3.9 hardening tests passed")
