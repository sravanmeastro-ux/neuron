"""V2 interrupt — stop phrases + AgentLoop abort."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_stop_phrases():
    from neuron.speech.interrupt import is_stop_phrase

    yes = [
        "Neuron, stop.",
        "neuron stop",
        "hey neuron stop",
        "stop neuron",
        "stop talking",
        "be quiet",
        "shut up",
        "silence",
        "halt",
        "abort",
        "cancel that",
        "never mind",
        "stop",
        "Stop!",
        "please stop",
    ]
    no = [
        "stop the video",
        "stop recording",
        "stop training",
        "open chrome",
        "play spotify",
    ]
    for t in yes:
        assert is_stop_phrase(t), f"should interrupt: {t!r}"
    for t in no:
        assert not is_stop_phrase(t), f"should NOT interrupt: {t!r}"
    print("OK stop phrases")


def test_request_clear():
    from neuron.speech import interrupt as i

    i.clear()
    assert not i.interrupted()
    gen = i.request(reason="test")
    assert i.interrupted()
    assert i.generation() == gen
    assert i.clear() is True
    assert not i.interrupted()
    print("OK request/clear")


def test_executor_aborts():
    from neuron.brain import executor, tool_registry
    from neuron.speech import interrupt as i

    tool_registry.reset_for_tests()
    import brain  # noqa
    tool_registry.ensure_bootstrapped()
    i.clear()
    i.request(reason="executor_test")
    er = executor.execute_plan({
        "steps": [
            {"action": "windows.get_monitors", "args": {}},
            {"action": "wait", "args": {"seconds": 1}},
        ],
    })
    assert er.errors and "interrupt" in er.errors[0].lower()
    assert er.steps_run and er.steps_run[0].get("interrupted")
    i.clear()
    print("OK executor abort")


def test_brain_stop():
    import brain
    from neuron.speech import interrupt as i

    i.clear()
    reply, acted = brain.handle_command("Neuron, stop.")
    assert reply == "__STOP_SPEECH__" and acted
    reply2, acted2 = brain.handle_command("stop talking")
    assert reply2 == "__STOP_SPEECH__" and acted2
    print("OK brain stop")


def test_loop_interrupted_flag():
    from neuron.brain.loop import run_opavr
    from neuron.speech import interrupt as i

    i.clear()
    i.request(reason="loop_test")
    say, acted, meta, goal = run_opavr(
        request="get monitors twice",
        plan={
            "say": "Checking.",
            "steps": [
                {"action": "windows.get_monitors", "args": {}},
                {"action": "windows.get_monitors", "args": {}},
            ],
        },
        confirmed=True,
    )
    assert meta.get("interrupted") or goal.status == "interrupted"
    assert "Stop" in (say or "")
    i.clear()
    print("OK loop interrupt", say, goal.status)


if __name__ == "__main__":
    test_stop_phrases()
    test_request_clear()
    test_executor_aborts()
    test_brain_stop()
    test_loop_interrupted_flag()
    print("ALL interrupt tests passed")
