"""Phase 1 NEURON brain smoke tests — normalize, registry, planner dry-run, agent loop."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_normalize_tool_arguments():
    from neuron.brain.normalize import normalize_plan

    plan = normalize_plan(
        [
            {"tool": "open_app", "arguments": {"application": "Blender"}},
            {"tool": "search_site", "arguments": {"url": "youtube", "q": "fluid sim"}},
        ]
    )
    assert plan["steps"][0]["action"] == "open_app"
    assert plan["steps"][0]["args"]["name"] == "Blender"
    assert plan["steps"][1]["args"]["site"] == "youtube"
    assert plan["steps"][1]["args"]["query"] == "fluid sim"
    print("OK normalize", plan["steps"])


def test_registry_open_app_schema():
    from neuron.brain import tool_registry
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    spec = tool_registry.get("open_app")
    assert spec is not None
    assert "name" in (spec.args_schema or {}) or "application" in str(spec.args_schema)
    assert spec.risk
    doc = tool_registry.tools_doc(20)
    assert "open_app" in doc
    print("OK registry schema", spec.risk)


def test_intent_and_deterministic_agent():
    from neuron.brain import agent, executor, tool_registry
    from neuron.brain.verifier import VerifyResult
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()

    with mock.patch.object(executor, "execute_plan") as ex, mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step",
        return_value=VerifyResult(True, "verified"),
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world",
        return_value={"app": "Notepad"},
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_goal",
        return_value=VerifyResult(True, "final goal verified"),
    ):
        from neuron.brain.executor import ExecutionResult

        er = ExecutionResult()
        er.outcomes = ["Opened Notepad."]
        er.steps_run = [{
            "action": "open_app",
            "args": {"name": "notepad"},
            "ok": True,
            "out": "Opened Notepad.",
        }]
        ex.return_value = er
        say, acted, meta = agent.run("open notepad", use_rules_fallback=False)
        assert acted
        assert meta["path"] in ("deterministic", "recipe")
        call_plan = ex.call_args[0][0]
        assert call_plan["steps"][0]["action"] == "open_app"
        print("OK deterministic agent", meta["path"], say)


def test_planner_youtube_mock():
    from neuron.brain import planner
    import brain_llm

    fake = {
        "say": "Searching YouTube.",
        "steps": [
            {"tool": "search_site", "arguments": {"site": "youtube", "query": "Blender fluid simulation tutorials"}},
        ],
    }
    with mock.patch.object(brain_llm, "is_enabled", return_value=True), mock.patch.object(
        brain_llm, "chat_json", return_value=json.dumps(fake)
    ):
        out = planner.plan("Open YouTube and search for Blender fluid simulation tutorials.")
    assert out is not None
    assert out["steps"][0]["action"] == "search_site"
    assert "fluid" in out["steps"][0]["args"]["query"].lower()
    print("OK planner mock", out["steps"])


def test_agent_llm_path_mock():
    from neuron.brain import agent, executor, tool_registry
    from neuron.brain.normalize import normalize_plan
    from neuron.brain.verifier import VerifyResult
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()

    fake_plan = normalize_plan(
        {
            "say": "Searching YouTube.",
            "steps": [
                {
                    "tool": "search_site",
                    "arguments": {
                        "site": "youtube",
                        "query": "Blender fluid simulation tutorials",
                    },
                }
            ],
        }
    )
    from neuron.brain.executor import ExecutionResult

    er = ExecutionResult()
    er.outcomes = ["Opened YouTube search."]
    er.steps_run = [{
        "action": "search_site",
        "args": {"site": "youtube", "query": "Blender fluid simulation tutorials"},
        "ok": True,
        "out": "Opened YouTube search.",
    }]

    with mock.patch("neuron.brain.planner.plan", return_value=fake_plan), mock.patch.object(
        executor, "execute_plan", return_value=er
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_execution_step",
        return_value=VerifyResult(True, "ok; url=youtube"),
    ), mock.patch(
        "neuron.brain.loop.verifier.observe_world",
        return_value={"url": "https://www.youtube.com/results"},
    ), mock.patch(
        "neuron.brain.loop.verifier.verify_goal",
        return_value=VerifyResult(True, "final goal verified"),
    ):
        say, acted, meta = agent.run(
            "Open YouTube and search for Blender fluid simulation tutorials.",
            use_rules_fallback=False,
        )
    assert acted
    assert meta["path"] == "llm"
    assert "search" in (say or "").lower() or say
    print("OK agent youtube search", meta["path"], say)


def test_rules_still_importable():
    import brain
    assert callable(brain.handle_command)
    print("OK handle_command wired")


if __name__ == "__main__":
    test_normalize_tool_arguments()
    test_registry_open_app_schema()
    test_intent_and_deterministic_agent()
    test_planner_youtube_mock()
    test_agent_llm_path_mock()
    test_rules_still_importable()
    print("\n=== Phase 1 brain tests passed ===")
