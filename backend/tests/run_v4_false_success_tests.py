"""V4.5 false-success attack suite.

Every case: tool/action reports ok, but world evidence does NOT support SUCCESS.
Required: FALSE_SUCCESS_COUNT == 0

No LIVE desktop control.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FALSE_SUCCESS_COUNT = 0


def _fail(msg: str) -> None:
    global FALSE_SUCCESS_COUNT
    FALSE_SUCCESS_COUNT += 1
    print(f"FALSE_SUCCESS: {msg}")


def _mons():
    return [
        {"id": 1, "left": 0, "top": 0, "width": 1920, "height": 1080, "primary": True, "roles": ["main"]},
        {"id": 2, "left": 1920, "top": 0, "width": 1920, "height": 1080, "primary": False, "roles": ["other"]},
    ]


def _world_chrome(mon=1, title="Chrome"):
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    reset_world_model()
    wm = DesktopWorldModel()
    left = 100 if mon == 1 else 2000
    wm.update_from_observe_dict(
        {
            "monitors": _mons(),
            "active_application": "Chrome",
            "windows": [{
                "hwnd": 55, "title": title, "app": "Chrome", "monitor_id": mon,
                "left": left, "top": 40, "width": 1000, "height": 700, "focused": True,
            }],
        }
    )
    return wm


def main() -> int:
    global FALSE_SUCCESS_COUNT
    FALSE_SUCCESS_COUNT = 0

    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify import VerificationEngine, derive_expectation
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    from neuron.v4.world.models import BrowserState, KnowledgeLevel

    eng = VerificationEngine()
    ok_ar = {"ok": True, "message": "Done."}

    cases = []

    # 1. click ok, nothing changes
    r = eng.verify(
        derive_expectation("click", {"text": "Submit"}),
        world=_world_chrome(),
        screen_diff={"changed": False, "change_score": 0},
        action_result=ok_ar,
        wait=False,
    )
    cases.append(("click no change", r))

    # 2. open_app ok, no window
    reset_world_model()
    empty = DesktopWorldModel()
    empty.update_from_observe_dict({"monitors": _mons(), "windows": []})
    r = eng.verify(
        derive_expectation("open_app", {"name": "Chrome"}),
        world=empty,
        action_result={"ok": True, "state": {"verified": False, "process": True}},
        wait=False,
    )
    cases.append(("open process no window", r))

    # 3. move shortcut ok, still monitor 1
    r = eng.verify(
        derive_expectation("move_window_to_monitor", {"name": "Chrome", "monitor": 2}),
        world=_world_chrome(mon=1),
        action_result=ok_ar,
        wait=False,
    )
    cases.append(("move still mon1", r))

    # 4. fullscreen key ok, media unknown / maximized only
    wm = _world_chrome(title="YouTube")
    st = wm.current
    st.browser = BrowserState(browser="Chrome", url="https://www.youtube.com/watch?v=x", fullscreen=None, knowledge=KnowledgeLevel.KNOWN)
    wm._current = st
    r = eng.verify(derive_expectation("youtube.fullscreen", {}), world=wm, action_result=ok_ar, wait=False)
    cases.append(("fullscreen unknown", r))

    # 5. browser ok, URL unchanged
    st.browser.url = "https://example.com"
    r = eng.verify(
        derive_expectation("browser_navigate", {"url": "https://www.youtube.com"}),
        world=wm,
        action_result=ok_ar,
        wait=False,
    )
    cases.append(("url unchanged", r))

    # 6. typing ok, wrong/missing field
    r = eng.verify(
        derive_expectation("type_text", {"text": "Blender", "element_id": "missing"}),
        world=_world_chrome(),
        action_result=ok_ar,
        wait=False,
    )
    cases.append(("type wrong field", r))

    # 7. trivial pixel change after click
    r = eng.verify(
        derive_expectation("uia_click", {}),
        world=_world_chrome(),
        screen_diff={"changed": True, "change_score": 0.02},
        action_result=ok_ar,
        wait=False,
    )
    cases.append(("trivial screen change", r))

    # 8. caller ok without verification on planner
    from neuron.v4.plan import HierarchicalPlanner, reset_hierarchical_planner, StepStatus
    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    plan = p.create_plan("open chrome")
    d = p.plan_next(plan, world=_world_chrome())
    # If already skipped, craft ACT artificially
    if d.grounded is None:
        plan = p.create_plan("mute")
        d = p.plan_next(plan, world=_world_chrome())
    p.apply_action_outcome(plan, d, ok=True)
    sg = next(s for s in plan.subgoals if s.subgoal_id == d.subgoal_id)
    if sg.status is StepStatus.SUCCEEDED:
        _fail("planner accepted caller ok without VerificationOutcome")
    cases.append(("planner caller-ok", type("R", (), {"status": VerificationOutcome.UNCERTAIN if sg.status is StepStatus.UNCERTAIN else VerificationOutcome.SUCCESS})()))

    print("False-success attack results:")
    for name, rep in cases:
        status = rep.status
        print(f"  {name}: {status.value}")
        if status is VerificationOutcome.SUCCESS:
            _fail(name)

    print(f"FALSE_SUCCESS_COUNT={FALSE_SUCCESS_COUNT}")
    if FALSE_SUCCESS_COUNT != 0:
        print("FAIL false-success suite")
        return 1
    print("PASS false-success suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
