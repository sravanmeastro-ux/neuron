"""Agent architecture unit tests — registry, safety, intent, verifier."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_catalog_and_registry():
    from neuron.catalog import LEGACY_EXECUTORS
    from neuron.brain import tool_registry
    tool_registry.reset_for_tests()
    # Import brain so legacy executors exist, then bootstrap
    import brain  # noqa: F401
    tool_registry.ensure_bootstrapped()
    names = set(tool_registry.names())
    for n in ("open_app", "youtube_home", "get_ui_tree", "run_powershell", "computer_use"):
        assert n in names, f"missing tool {n}"
    assert "open_app" in LEGACY_EXECUTORS
    print("OK registry", len(names), "tools")


def test_safety_blocks_shell():
    from neuron.safety import policy
    ok, reason = policy.allow("run_shell", {"command": "rm -rf /"}, confirmed=False)
    assert not ok
    ok2, _ = policy.allow("run_powershell", {"command": "Get-Process"}, confirmed=False)
    assert ok2
    ok3, reason3 = policy.allow("run_powershell", {"command": "Remove-Item C:\\Windows -Recurse"}, confirmed=True)
    assert not ok3
    print("OK safety", reason[:40])


def test_intent_open():
    from neuron.brain.intent import understand
    i = understand("open notepad")
    assert i.kind in ("deterministic", "recipe", "llm")
    if i.kind == "deterministic":
        assert i.action == "open_app"
        assert "notepad" in i.args.get("name", "")
    print("OK intent", i.kind, i.action)


def test_verifier_error():
    from neuron.brain.verifier import verify_step
    ok, note = verify_step({"action": "open_app", "args": {"name": "x"}}, None, "boom")
    assert not ok and "boom" in note
    print("OK verifier")


def test_sqlite_memory():
    from neuron.memory import store
    store.init_db()
    store.remember("agent_test_key", "agent_test_val")
    assert store.recall("agent_test_key") == "agent_test_val"
    store.log_tool_run("open_app", {"name": "x"}, ok=True, detail="ok")
    runs = store.recent_tool_runs(3)
    assert runs
    print("OK sqlite", runs[0][:50])


def test_executor_unknown():
    from neuron.brain import executor, tool_registry
    import brain  # noqa
    tool_registry.ensure_bootstrapped()
    er = executor.execute_plan({"steps": [{"action": "not_a_real_tool_zz", "args": {}}]})
    assert "not_a_real_tool_zz" in er.unknown
    print("OK executor unknown")


def test_normalize_aliases():
    from neuron.brain.normalize import normalize_plan
    p = normalize_plan({"tool": "open_app", "arguments": {"application": "Blender"}})
    assert p["steps"][0]["args"]["name"] == "Blender"
    print("OK normalize aliases")


if __name__ == "__main__":
    test_catalog_and_registry()
    test_safety_blocks_shell()
    test_intent_open()
    test_verifier_error()
    test_sqlite_memory()
    test_executor_unknown()
    test_normalize_aliases()
    print("\n=== agent tests passed ===")
