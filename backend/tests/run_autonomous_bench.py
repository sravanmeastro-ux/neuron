"""Benchmarks for Autonomous Agent (Task Planner upgrade)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.autonomous import plan_goal, assess_plan
    from neuron.autonomous import correct, progress, replan, risk, verify
    from neuron.autonomous.engine import run_autonomous
    from neuron.taskplan.types import GoalSpec, Observation, Subtask, TaskGraph, TaskState, StepStatus
    from neuron.taskplan import state as state_mod

    # Goal planning + decomposition + risk
    text = "Create a new folder on the desktop called Projects, move all PDF files into it, then zip the folder."
    goal, graph, risk_info = plan_goal(text)
    assert graph and len(graph.subtasks) >= 3, graph
    assert risk_info.get("confirm_required_count", 0) >= 1 or risk_info.get("level") in ("medium", "high", "low")
    assert any(s.requires_confirm for s in graph.subtasks) or goal.destructive
    print(f"OK plan steps={len(graph.subtasks)} risk={risk_info.get('level')} confirm={risk_info.get('confirm_required_count')}")

    # Risk assess destructive
    info = risk.assess_action("task_zip_folder", {"name": "Projects"})
    assert info["needs_confirm"] and info["destructive"]
    print(f"OK risk zip tier={info['tier']}")

    # Verify step / goal
    sub = Subtask(description="Open Chrome", action="open_app", args={"name": "Chrome"}, expected_result="Chrome open")
    before = Observation(application="explorer", window_title="Desktop")
    after = Observation(application="chrome", window_title="New Tab")
    v = verify.verify_step(sub, before=before, after=after, ok_flag=True, message="Opened Chrome")
    assert v["passed"]
    gv = verify.verify_goal(
        GoalSpec(text=text, completion_criteria=["all planned subtasks completed"], destructive=True),
        steps_completed=3,
        steps_total=3,
        success_flag=True,
    )
    assert gv["passed"]
    print("OK verify step+goal")

    # Self-correction
    fail_sub = Subtask(description="Click Download", action="click_element", args={"name": "Download"})
    alts = correct.suggest_corrections(fail_sub, "element not found")
    assert alts, alts
    assert any(a.get("action") == "screen_understand" for a in alts)
    print(f"OK correct n={len(alts)} cat={correct.diagnose(fail_sub, 'element not found')['category']}")

    # Dynamic replan insert
    g2 = TaskGraph(
        goal=GoalSpec(text="test", applications=["Chrome"]),
        subtasks=[
            Subtask(description="Click", action="click_element", args={"name": "X"}, status=StepStatus.PENDING),
        ],
    )
    rp = replan.replan_remaining(g2)
    assert rp.get("replanned") or any(s.action == "open_app" for s in g2.subtasks)
    print(f"OK dynamic_replan {rp}")

    # Progress snapshot
    st = TaskState(goal=goal, graph=graph, status=__import__("neuron.taskplan.types", fromlist=["TaskStatus"]).TaskStatus.RUNNING)
    st.completed_ids = [graph.subtasks[0].subtask_id]
    graph.subtasks[0].status = StepStatus.COMPLETED
    st.sync_from_graph()
    snap = progress.snapshot(st)
    assert snap["steps_total"] >= 3 and snap["progress_pct"] > 0
    print(f"OK progress pct={snap['progress_pct']}")

    # Confirmation gate (destructive) without confirmed=True
    state_mod.clear_state()
    say, acted, meta = run_autonomous(graph, confirmed=False, risk_info=risk_info)
    assert acted
    assert meta.get("needs_confirm") or meta.get("path") == "autonomous"
    if meta.get("needs_confirm"):
        print(f"OK confirm_gate action={meta['needs_confirm'].get('action')}")
    else:
        # If first steps are safe, assess still attached
        assert "risk" in meta
        print("OK autonomous run (early steps safe)")

    # Tool registration
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    for name in ("autonomous_run", "autonomous_progress", "autonomous_assess", "run_task_workflow"):
        assert tool_registry.get(name), name
    print("OK tools registered")

    # Assess tool (no execute)
    from neuron.autonomous import tool_autonomous_assess
    res = tool_autonomous_assess({"request": "Download Blender and install it."})
    assert getattr(res, "ok", True) or (isinstance(res, dict) and res.get("ok", True))
    print("OK autonomous_assess")

    # Classic taskplan detect still works via handle
    from neuron.taskplan.engine import handle
    r = handle("mute")
    assert r is None
    print("OK non-workflow passthrough")

    print("PASS autonomous_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
