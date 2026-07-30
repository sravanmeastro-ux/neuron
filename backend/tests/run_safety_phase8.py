"""Phase 8 safety tier tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_safe_actions():
    from neuron.safety import policy

    for name, args in (
        ("open_app", {"name": "chrome"}),
        ("focus_app", {"name": "notepad"}),
        ("scroll", {"direction": "down"}),
        ("youtube.search", {"query": "blender"}),
        ("windows.move_to_monitor", {"name": "chrome", "monitor": 2}),
        ("run_powershell", {"command": "Get-Process"}),
    ):
        ok, reason = policy.allow(name, args, confirmed=False)
        assert ok, f"{name} should be safe: {reason}"
        assert policy.classify(name, args).tier == "safe"
    print("OK safe")


def test_confirm_actions():
    from neuron.safety import policy

    ok, reason = policy.allow("create_file", {"name": "notes.txt", "content": "hi"}, confirmed=False)
    assert not ok and "confirm" in reason.lower()
    ok2, _ = policy.allow("create_file", {"name": "notes.txt"}, confirmed=True)
    assert ok2

    ok3, reason3 = policy.allow(
        "computer_use",
        {"goal": "send a message to Alex saying hello"},
        confirmed=False,
    )
    assert not ok3
    assert policy.classify("computer_use", {"goal": "send a message to Alex"}).tier == "confirm"

    ok4, _ = policy.allow("click_text", {"text": "Send"}, confirmed=False)
    assert not ok4
    print("OK confirm", reason[:50])


def test_blocked_never_overrides():
    from neuron.safety import policy

    for args in (
        {"command": "shutdown /s /t 0"},
        {"command": "Remove-Item C:\\Windows -Recurse -Force"},
        {"goal": "send $500 via paypal send"},
        {"text": "format C: drive now"},
    ):
        tool = "run_shell" if "command" in args else "computer_use"
        ok, reason = policy.allow(tool, args, confirmed=True)
        assert not ok, f"should stay blocked: {args} -> {reason}"
        assert policy.classify(tool, args).tier == "blocked"
    print("OK blocked")


def test_high_shell():
    from neuron.safety import policy

    ok, reason = policy.allow("run_shell", {"command": "echo hi"}, confirmed=False)
    assert not ok
    assert policy.classify("run_shell", {"command": "echo hi"}).tier == "high"
    ok2, _ = policy.allow("run_shell", {"command": "echo hi"}, confirmed=True)
    assert ok2
    print("OK high shell")


def test_failsafe():
    from neuron.safety.failsafe import ensure_failsafe, power_actions_disabled_message
    msg = ensure_failsafe()
    assert "FAILSAFE" in msg or "unavailable" in msg.lower()
    assert "disabled" in power_actions_disabled_message().lower()
    print("OK failsafe")


def test_executor_confirm_path():
    from neuron.brain import executor, tool_registry
    from neuron.safety import policy

    tool_registry.reset_for_tests()
    import brain  # noqa
    tool_registry.ensure_bootstrapped()
    policy.clear_pending()
    er = executor.execute_plan({
        "steps": [{"action": "create_file", "args": {"name": "x.txt", "content": "a"}}],
    })
    assert er.needs_confirm
    assert er.needs_confirm.get("tier") == "confirm"
    pending = policy.get_pending()
    assert pending and pending["action"] == "create_file"
    policy.clear_pending()
    print("OK executor confirm gate")


def test_agent_safety_regression():
    from neuron.safety import policy

    ok, reason = policy.allow("run_shell", {"command": "rm -rf /"}, confirmed=False)
    assert not ok
    ok3, reason3 = policy.allow(
        "run_powershell",
        {"command": "Remove-Item C:\\Windows -Recurse"},
        confirmed=True,
    )
    assert not ok3
    print("OK agent safety regression", reason[:40])


if __name__ == "__main__":
    test_safe_actions()
    test_confirm_actions()
    test_blocked_never_overrides()
    test_high_shell()
    test_failsafe()
    test_executor_confirm_path()
    test_agent_safety_regression()
    print("ALL Phase 8 safety tests passed")
