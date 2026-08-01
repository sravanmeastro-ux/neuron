"""V4.4 hierarchical planner smoke — NO LIVE CONTROL.

Simulates:
  Open YouTube on monitor 2, search Blender beginner tutorials,
  play the first video and fullscreen it.

Uses mock world updates + mock tool results only.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _mons():
    return [
        {
            "id": 1, "left": 0, "top": 0, "width": 1920, "height": 1080,
            "primary": True, "roles": ["main", "primary", "left"],
        },
        {
            "id": 2, "left": 1920, "top": 0, "width": 2560, "height": 1440,
            "primary": False, "roles": ["secondary", "right", "other"],
        },
    ]


def _set_world(*, youtube=False, monitor_id=1, playing=False, fullscreen=False):
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    from neuron.v4.world.models import BrowserState, KnowledgeLevel

    reset_world_model()
    wm = DesktopWorldModel()
    title = "YouTube - Chrome" if youtube else "New Tab - Chrome"
    if playing:
        title = "Blender Beginner Tutorial - YouTube - Chrome"
    left = 100 if int(monitor_id) == 1 else 2000
    wm.update_from_observe_dict(
        {
            "monitors": _mons(),
            "active_application": "Chrome",
            "window": title,
            "hwnd": 55,
            "focused_monitor": monitor_id,
            "windows": [
                {
                    "hwnd": 55,
                    "title": title,
                    "app": "Chrome",
                    "monitor_id": monitor_id,
                    "left": left,
                    "top": 40,
                    "width": 1200,
                    "height": 800,
                    "focused": True,
                }
            ],
            "browser_url": "https://www.youtube.com/watch?v=abc" if playing else (
                "https://www.youtube.com/results?search_query=blender" if youtube else ""
            ),
            "browser_title": title if youtube else "",
        }
    )
    if youtube or playing:
        st = wm.current
        st.browser = BrowserState(
            browser="Chrome",
            url=st.browser.url if st.browser else "https://www.youtube.com",
            tab_title=title,
            knowledge=KnowledgeLevel.KNOWN,
        )
        if playing:
            st.browser.url = "https://www.youtube.com/watch?v=abc"
        wm._current = st
    return wm


def main() -> int:
    from neuron.v4.plan import (
        DecisionKind,
        HierarchicalPlanner,
        StepStatus,
        reset_hierarchical_planner,
    )

    reset_hierarchical_planner()
    planner = HierarchicalPlanner(allow_llm=False)
    goal_text = (
        "Open YouTube on monitor 2, search for Blender beginner tutorials, "
        "play the first video and fullscreen it."
    )
    plan = planner.create_plan(goal_text)
    print("GOAL")
    print(f"  {plan.goal.text}")
    print(f"  plan_id={plan.plan_id} source={plan.source} subgoals={len(plan.subgoals)}")
    for sg in plan.subgoals:
        print(f"  - [{sg.subgoal_id}] {sg.description} ({sg.intent})")

    # Start: no useful world → observe
    wm = _set_world(youtube=False, monitor_id=1)
    # Clear windows to force UNKNOWN open? Actually chrome exists on mon1 —
    # ensure_youtube: youtube_loaded_known False → need open/nav
    # Better: empty-ish then progressive updates

    reset_hierarchical_planner()
    planner = HierarchicalPlanner()
    plan = planner.create_plan(goal_text)

    # Phase 0: empty world
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    reset_world_model()
    empty = DesktopWorldModel()

    step = 0
    max_steps = 20
    while step < max_steps:
        step += 1
        d = planner.plan_next(plan, world=empty if step == 1 else wm)
        print()
        print(f"--- tick {step} ---")
        print(f"SUBGOAL: {d.subgoal_description or '(none)'}")
        print(f"DECISION: {d.kind.value} — {d.reason}")
        if d.grounded:
            print(f"ACTION: {d.grounded.tool} {d.grounded.arguments}")
        if d.kind is DecisionKind.COMPLETE:
            print("COMPLETE")
            break
        if d.kind is DecisionKind.CANCELLED:
            print("CANCELLED")
            return 1
        if d.kind is DecisionKind.FAIL:
            print("FAIL")
            return 1
        if d.kind is DecisionKind.CLARIFY:
            print(f"CLARIFY: {d.clarify_prompt}")
            return 1
        if d.kind is DecisionKind.OBSERVE:
            print("MOCK RESULT: observation refresh")
            # Progressive world: after first observe, Chrome+YouTube on mon2
            wm = _set_world(youtube=True, monitor_id=2)
            print("WORLD UPDATE: YouTube on monitor 2")
            # If observe was the final confirm subgoal, mark it
            if d.subgoal_id:
                for sg in plan.subgoals:
                    if sg.subgoal_id == d.subgoal_id and sg.intent == "observe":
                        planner.mark_subgoal(plan, d.subgoal_id, StepStatus.SUCCEEDED)
            continue
        if d.kind is DecisionKind.ACT and d.grounded:
            tool = d.grounded.tool
            print(f"MOCK RESULT: {tool} ok")
            from neuron.v4.verify import get_verification_engine
            from neuron.v4.types import ActionResult
            # Progressive world before verify
            if "search" in tool:
                wm = _set_world(youtube=True, monitor_id=2)
                print("WORLD UPDATE: search results visible")
            elif "play" in tool:
                wm = _set_world(youtube=True, monitor_id=2, playing=True)
                print("WORLD UPDATE: video playing")
            elif "fullscreen" in tool:
                wm = _set_world(youtube=True, monitor_id=2, playing=True, fullscreen=True)
                # media fullscreen known for smoke
                from neuron.v4.world.models import BrowserState, KnowledgeLevel
                st = wm.current
                st.browser = BrowserState(
                    browser="Chrome",
                    url="https://www.youtube.com/watch?v=abc",
                    tab_title="Blender",
                    fullscreen=True,
                    knowledge=KnowledgeLevel.KNOWN,
                )
                wm._current = st
                print("WORLD UPDATE: fullscreen")
            elif "move" in tool or "monitor" in tool:
                wm = _set_world(youtube=True, monitor_id=2)
                print("WORLD UPDATE: window on monitor 2")
            elif "open" in tool or "home" in tool or "website" in tool:
                wm = _set_world(youtube=True, monitor_id=1)
                print("WORLD UPDATE: YouTube available")
            rep = get_verification_engine().verify_grounded_action(
                d.grounded,
                world=wm,
                action_result=ActionResult(ok=True, message="mock"),
                wait=False,
            )
            print(f"VERIFY: {rep.status.value} — {rep.reason[:80]}")
            planner.apply_verification(plan, d, rep)
            continue
        if d.kind is DecisionKind.WAIT:
            print("WAIT (dependency)")
            break
        print(f"Unhandled decision {d.kind}")
        break
    else:
        print("FAIL: exceeded max ticks")
        return 1

    print()
    print("Final subgoal statuses:")
    for sg in plan.subgoals:
        print(f"  {sg.status.value:10} {sg.description}")
    print(f"Plan status: {plan.status.value}")
    print("Planner smoke PASS (no live control).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
