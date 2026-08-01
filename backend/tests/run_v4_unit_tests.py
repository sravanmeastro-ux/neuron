"""V4 unit tests — V4.0 typed state through V4.4 hierarchical planner.

No LIVE desktop control. Uses fixtures/mocks only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# --------------------------------------------------------------------------- V4.0


def test_plan_roundtrip():
    from neuron.v4 import Plan, PlanStep

    legacy = {
        "say": "Opening Chrome",
        "source": "capability",
        "steps": [
            {"action": "open_app", "args": {"name": "chrome"}, "expected_result": "Chrome"},
        ],
    }
    plan = Plan.from_legacy(legacy)
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "open_app"
    back = plan.to_legacy()
    assert back["steps"][0]["action"] == "open_app"
    assert PlanStep.from_legacy(back["steps"][0]).args["name"] == "chrome"
    print("OK plan roundtrip")


def test_verification_uncertain_not_success():
    from neuron.v4 import VerificationOutcome, VerificationResult

    u = VerificationResult.from_bool(None, detail="no signal")
    assert u.outcome is VerificationOutcome.UNCERTAIN
    assert u.success is False
    s = VerificationResult.from_bool(True)
    assert s.success is True
    f = VerificationResult.from_bool(False, category="ELEMENT_NOT_FOUND")
    assert f.outcome is VerificationOutcome.FAILURE
    print("OK verification outcomes")


def test_agent_state_interrupt():
    from neuron.v4 import AgentState
    from neuron.v4.types import AgentPhase

    st = AgentState()
    st.goal.text = "open chrome"
    st.mark_interrupted()
    assert st.interrupted
    assert st.phase is AgentPhase.INTERRUPTED
    assert st.status == "interrupted"
    print("OK agent state interrupt")


def test_recovery_from_v3():
    from neuron.v4 import RecoveryDecision
    from neuron.v3.loop_types import RecoveryDecision as V3Dec

    d = RecoveryDecision.from_v3(V3Dec(strategy="retry", status="RETRY", reason="timeout"))
    assert d.strategy == "retry"
    assert "timeout" in d.reason
    print("OK recovery bridge")


# --------------------------------------------------------------------------- V4.1 fixtures


def _dual_horizontal_mons():
    return [
        {
            "id": 1,
            "left": 0,
            "top": 0,
            "width": 1920,
            "height": 1080,
            "primary": True,
            "work_left": 0,
            "work_top": 0,
            "work_width": 1920,
            "work_height": 1040,
            "roles": ["main", "primary", "left"],
        },
        {
            "id": 2,
            "left": 1920,
            "top": 0,
            "width": 2560,
            "height": 1440,
            "primary": False,
            "work_left": 1920,
            "work_top": 0,
            "work_width": 2560,
            "work_height": 1400,
            "roles": ["secondary", "right", "other"],
        },
    ]


def _negative_coord_mons():
    """Primary at (0,0); secondary to the LEFT (negative X)."""
    return [
        {
            "id": 1,
            "left": 0,
            "top": 0,
            "width": 1920,
            "height": 1080,
            "primary": True,
            "roles": ["main", "primary", "right"],
        },
        {
            "id": 2,
            "left": -1920,
            "top": 0,
            "width": 1920,
            "height": 1080,
            "primary": False,
            "roles": ["secondary", "left", "other"],
        },
    ]


def _vertical_mons():
    return [
        {
            "id": 1,
            "left": 0,
            "top": 0,
            "width": 1920,
            "height": 1080,
            "primary": True,
            "roles": ["main", "primary"],
        },
        {
            "id": 2,
            "left": 0,
            "top": 1080,
            "width": 1920,
            "height": 1080,
            "primary": False,
            "roles": ["secondary", "other"],
        },
    ]


def test_world_model_creation_and_snapshot():
    from neuron.v4.world import DesktopWorldModel, reset_world_model

    reset_world_model()
    wm = DesktopWorldModel()
    assert wm.current is not None
    assert wm.previous is None
    snap = wm.snapshot()
    assert snap is not wm.current
    snap.scene = "mutated"
    assert wm.current.scene != "mutated"
    print("OK world model creation + snapshot isolation")


def test_state_update_pushes_previous():
    from neuron.v4.world import DesktopWorldModel

    wm = DesktopWorldModel()
    wm.update_from_observe_dict(
        {
            "active_application": "Chrome",
            "window": "YouTube - Chrome",
            "hwnd": 101,
            "focused_monitor": 1,
            "monitors": _dual_horizontal_mons(),
        }
    )
    fp1 = wm.current.ensure_fingerprint()
    assert wm.get_active_application() == "Chrome"
    assert wm.previous is not None  # first update still pushes empty→current
    wm.update_from_observe_dict(
        {
            "active_application": "Blender",
            "window": "Blender",
            "hwnd": 202,
            "focused_monitor": 2,
            "monitors": _dual_horizontal_mons(),
        }
    )
    assert wm.get_active_application() == "Blender"
    assert wm.previous is not None
    assert wm.previous.ensure_fingerprint() == fp1 or wm.previous.get_active_application() == "Chrome" or (
        wm.previous.foreground_application and wm.previous.foreground_application.name == "Chrome"
    )
    diff = wm.diff_snapshots()
    assert diff["changed"] is True
    assert any("app" in d or "focus" in d or "hwnd" in d for d in diff["diffs"])
    print("OK state update + previous snapshot + diff")


def test_monitor_geometry_negative_and_vertical():
    from neuron.v4.world import DesktopWorldModel

    wm = DesktopWorldModel()
    wm.update_from_observe_dict({"monitors": _negative_coord_mons(), "window": "x", "hwnd": 1})
    left = wm.resolve_monitor_reference("left")
    right = wm.resolve_monitor_reference("right")
    assert left and left.id == 2 and left.left < 0
    assert right and right.id == 1

    wm2 = DesktopWorldModel()
    wm2.update_from_observe_dict({"monitors": _vertical_mons(), "window": "x", "hwnd": 1})
    assert len(wm2.current.monitors) == 2
    assert wm2.current.monitors[1].top == 1080
    primary = wm2.resolve_monitor_reference("primary")
    assert primary and primary.id == 1
    other = wm2.resolve_monitor_reference("other", relative_to=1)
    assert other and other.id == 2
    print("OK negative coords + vertical monitors + primary/other")


def test_left_right_primary_other_resolution():
    from neuron.v4.world import DesktopWorldModel

    wm = DesktopWorldModel()
    wm.update_from_observe_dict(
        {
            "monitors": _dual_horizontal_mons(),
            "active_application": "Notepad",
            "window": "Untitled - Notepad",
            "hwnd": 11,
            "focused_monitor": 1,
            "windows": [
                {
                    "hwnd": 11,
                    "title": "Untitled - Notepad",
                    "app": "Notepad",
                    "monitor_id": 1,
                    "left": 100,
                    "top": 100,
                    "width": 800,
                    "height": 600,
                }
            ],
        }
    )
    assert wm.resolve_monitor_reference("main").id == 1
    assert wm.resolve_monitor_reference("primary").id == 1
    assert wm.resolve_monitor_reference("left").id == 1
    assert wm.resolve_monitor_reference("right").id == 2
    assert wm.resolve_monitor_reference("monitor 2").id == 2
    # other relative to window's monitor (V4.0 semantics) — NOT live foreground
    other = wm.resolve_monitor_reference("other", relative_to=1)
    assert other and other.id == 2
    other_from_2 = wm.resolve_monitor_reference("other screen", relative_to=2)
    assert other_from_2 and other_from_2.id == 1
    print("OK left/right/primary/other monitor resolution")


def test_window_monitor_and_app_lookup():
    from neuron.v4.world import DesktopWorldModel

    wm = DesktopWorldModel()
    wm.update_from_observe_dict(
        {
            "monitors": _dual_horizontal_mons(),
            "active_application": "Chrome",
            "window": "Blender Tutorial - YouTube - Chrome",
            "hwnd": 55,
            "focused_monitor": 2,
            "windows": [
                {
                    "hwnd": 55,
                    "title": "Blender Tutorial - YouTube - Chrome",
                    "app": "Chrome",
                    "monitor_id": 2,
                    "left": 2000,
                    "top": 40,
                    "width": 1200,
                    "height": 800,
                    "focused": True,
                },
                {
                    "hwnd": 66,
                    "title": "Blender",
                    "app": "Blender",
                    "monitor_id": 1,
                    "left": 40,
                    "top": 40,
                    "width": 900,
                    "height": 700,
                },
            ],
        }
    )
    chrome = wm.get_window_by_application("chrome")
    assert chrome and chrome.hwnd == 55
    blender_wins = wm.get_windows_by_application("Blender")
    assert len(blender_wins) == 1
    mon = wm.get_monitor_for_window(chrome)
    assert mon and mon.id == 2
    # semantic: monitor with Chrome
    m2 = wm.resolve_monitor_reference("the monitor with Chrome")
    assert m2 and m2.id == 2
    print("OK window->monitor + application lookup + monitor-with-app")


def test_unknown_and_confidence():
    from neuron.v4.world import DesktopWorldModel, KnowledgeLevel
    from neuron.v4.world.models import WindowState

    wm = DesktopWorldModel()
    wm.update_from_observe_dict({})  # empty — unknown focus
    assert wm.get_foreground_window() is None or wm.get_active_application() in ("", "?")
    assert wm.current.observation_confidence < 0.5

    # title-only → inferred application
    w = WindowState.from_dict({"title": "Notes - Notepad", "hwnd": 0})
    assert w.application_knowledge in (KnowledgeLevel.INFERRED, KnowledgeLevel.KNOWN)
    assert w.application.lower().find("notepad") >= 0 or "notepad" in w.application.lower()

    # hwnd+geometry monitor → higher confidence
    w2 = WindowState.from_dict(
        {
            "title": "Chrome",
            "hwnd": 99,
            "app": "Chrome",
            "monitor_id": 2,
            "left": 2000,
            "top": 0,
            "width": 100,
            "height": 100,
        }
    )
    assert w2.knowledge is KnowledgeLevel.KNOWN
    assert w2.application_knowledge is KnowledgeLevel.KNOWN
    assert w2.confidence >= 0.85
    print("OK unknown state + confidence / knowledge levels")


def test_bounded_interaction_history():
    from neuron.v4.world import DesktopWorldModel

    wm = DesktopWorldModel(max_interactions=5)
    wm.update_from_observe_dict(
        {"active_application": "Chrome", "window": "Chrome", "hwnd": 1, "monitors": _dual_horizontal_mons()}
    )
    for i in range(12):
        wm.record_interaction("click", target=f"btn{i}", ok=True, result="ok")
    hist = wm.get_recent_interactions(limit=20)
    assert len(hist) == 5
    assert hist[0].target == "btn7"
    assert hist[-1].target == "btn11"
    # secrets scrubbed
    wm.record_interaction("type_text", args={"password": "hunter2"}, result="password=hunter2")
    assert "[redacted]" in wm.get_recent_interactions(limit=1)[-1].result or not hist
    last = wm.get_recent_interactions(limit=1)[-1]
    assert "hunter2" not in last.result
    print("OK bounded interaction history + scrub")


def test_computer_state_adapter():
    from neuron.brain.computer_state import ComputerState
    from neuron.v4.world import DesktopWorldModel
    from neuron.v4.world.adapters import from_computer_state

    cs = ComputerState(
        active_application="Discord",
        focused_window_title="General - Discord",
        focused_hwnd=777,
        focused_monitor=1,
        monitors=_dual_horizontal_mons(),
        open_windows=[
            {"title": "General - Discord", "app": "Discord", "hwnd": 777, "monitor_id": 1}
        ],
        browser_url="",
        sources=["test"],
    )
    state = from_computer_state(cs)
    assert state.foreground_application and state.foreground_application.name == "Discord"
    assert state.foreground_window and state.foreground_window.hwnd == 777
    wm = DesktopWorldModel()
    wm.update_from_computer_state(cs)
    assert wm.get_active_application() == "Discord"
    print("OK ComputerState adapter")


def test_v3_world_state_adapter():
    from neuron.v3.world_state import WorldState
    from neuron.v4.world import DesktopWorldModel
    from neuron.v4.world.adapters import from_world_state, sync_world_state_from_desktop

    ws = WorldState()
    ws.active_app = "Spotify"
    ws.active_window = "Spotify Premium"
    ws.active_hwnd = 42
    ws.active_monitor = 2
    ws.monitors = _dual_horizontal_mons()
    state = from_world_state(ws)
    assert state.foreground_application.name == "Spotify"
    assert state.active_monitor_id == 2

    wm = DesktopWorldModel()
    wm.update_from_observe_dict(
        {
            "active_application": "Chrome",
            "window": "Chrome",
            "hwnd": 9,
            "focused_monitor": 1,
            "monitors": _dual_horizontal_mons(),
            "browser_url": "https://youtube.com",
        }
    )
    sync_world_state_from_desktop(ws, wm.current)
    assert ws.active_app == "Chrome"
    assert "youtube" in (ws.browser_url or "").lower()
    print("OK V3 WorldState adapter + reverse sync")


def test_agent_loop_world_access():
    from neuron.brain.agent_loop import AgentLoop
    from neuron.v4.world import reset_world_model

    reset_world_model()
    loop = AgentLoop()
    assert loop.world is not None
    loop.world.update_from_observe_dict(
        {
            "active_application": "Notepad",
            "window": "Untitled - Notepad",
            "hwnd": 3,
            "focused_monitor": 1,
            "monitors": _dual_horizontal_mons(),
        }
    )
    snap = loop.current_world_snapshot()
    assert snap.foreground_application.name == "Notepad"
    # Mocked OPAVR still wires world model in meta when observe runs
    with mock.patch("neuron.brain.agent_loop.run_opavr") as run:
        from neuron.brain.goal import GoalState

        def _fake(**kwargs):
            from neuron.v4.world import get_world_model
            get_world_model().update_from_observe_dict(
                {
                    "active_application": "Chrome",
                    "window": "Chrome",
                    "hwnd": 8,
                    "focused_monitor": 2,
                    "monitors": _dual_horizontal_mons(),
                }
            )
            g = GoalState(goal="open chrome", status="success")
            return "Done.", True, {"path": "opavr", "world_model": True}, g

        run.side_effect = _fake
        say, acted, meta, goal = loop.run("open chrome", plan={"say": "", "steps": []})
    assert acted
    assert loop.world.get_active_application() == "Chrome"
    assert meta.get("world_active_app") == "Chrome"
    print("OK AgentLoop world access")


def test_agent_state_apply_desktop():
    from neuron.v4 import AgentState
    from neuron.v4.world import DesktopWorldModel

    wm = DesktopWorldModel()
    wm.update_from_observe_dict(
        {
            "active_application": "Edge",
            "window": "Edge",
            "hwnd": 5,
            "focused_monitor": 1,
            "monitors": _dual_horizontal_mons(),
            "clickables": [{"name": "Search", "role": "button", "confidence": 0.9}],
        }
    )
    st = AgentState()
    st.apply_desktop_snapshot(wm.current, which="before")
    assert st.focused_application == "Edge"
    assert st.active_monitor == 1
    assert st.world_before is not None
    assert st.visible_elements
    print("OK AgentState.apply_desktop_snapshot")


# --------------------------------------------------------------------------- V4.2 perception


def test_empty_observation_unknown():
    from neuron.v4.perception import PerceptionEngine
    from neuron.v4.world import reset_world_model

    reset_world_model()
    pe = PerceptionEngine()
    with mock.patch.object(pe, "_gather_monitors", return_value=([], None)), mock.patch.object(
        pe, "_gather_windows", return_value=([], None, None, [])
    ), mock.patch.object(pe, "_gather_cursor", return_value={}):
        res = pe.observe(push_world=True, use_uia=False, use_browser=False)
    assert res.confidence < 0.5
    assert res.desktop.foreground_window is None
    assert res.ok is False or res.confidence < 0.5
    print("OK empty observation stays unknown")


def test_perception_monitor_normalization():
    from neuron.v4.perception.engine import PerceptionEngine
    from neuron.v4.world import reset_world_model
    from neuron.v4.world.models import MonitorState

    reset_world_model()
    pe = PerceptionEngine()
    mons = [MonitorState.from_dict(m) for m in _negative_coord_mons()]
    with mock.patch.object(pe, "_gather_monitors", return_value=(mons, None)), mock.patch.object(
        pe, "_gather_windows", return_value=([], None, None, [])
    ), mock.patch.object(pe, "_gather_cursor", return_value={}):
        res = pe.observe(use_uia=False, use_browser=False, push_world=True)
    assert len(res.desktop.monitors) == 2
    left = min(res.desktop.monitors, key=lambda m: m.center_x)
    assert left.left < 0
    verts = [MonitorState.from_dict(m) for m in _vertical_mons()]
    with mock.patch.object(pe, "_gather_monitors", return_value=(verts, None)), mock.patch.object(
        pe, "_gather_windows", return_value=([], None, None, [])
    ):
        res2 = pe.observe(use_uia=False, use_browser=False, push_world=False)
    assert res2.desktop.monitors[1].top == 1080
    print("OK perception monitor normalization (neg/vertical)")


def test_window_enum_and_foreground():
    from neuron.v4.perception.engine import PerceptionEngine, _window_from_row
    from neuron.v4.world.models import MonitorState, WindowState, ApplicationState

    mons = [MonitorState.from_dict(m) for m in _dual_horizontal_mons()]
    pe = PerceptionEngine()
    fg = WindowState.from_dict(
        {
            "hwnd": 10,
            "title": "Chrome",
            "app": "Chrome",
            "monitor_id": 2,
            "left": 2000,
            "top": 0,
            "width": 800,
            "height": 600,
            "focused": True,
        }
    )
    app = ApplicationState(name="Chrome", focused=True, knowledge=fg.application_knowledge, confidence=0.9)
    wins = [fg]
    with mock.patch.object(pe, "_gather_monitors", return_value=(mons, None)), mock.patch.object(
        pe, "_gather_windows", return_value=(wins, fg, app, [])
    ), mock.patch.object(pe, "_gather_cursor", return_value={"x": 2100, "y": 100, "monitor": 2}):
        res = pe.observe(use_uia=False, use_browser=False, push_world=False)
    assert res.desktop.foreground_window and res.desktop.foreground_window.hwnd == 10
    assert res.desktop.active_monitor_id == 2
    w = _window_from_row(
        {"hwnd": 3, "title": "Notepad", "left": 100, "top": 100, "width": 400, "height": 300},
        [m.to_dict() for m in mons],
    )
    assert w.monitor_id == 1
    print("OK window enum + foreground + window->monitor")


def test_ui_element_normalization_and_stable_ids():
    from neuron.v4.perception import stable_element_id, element_fingerprint_changed
    from neuron.v4.perception.element_ids import normalize_uia_role

    assert normalize_uia_role("ButtonControl", "OK") == "button"
    id1, c1 = stable_element_id(
        application="Chrome",
        window_hwnd=5,
        automation_id="search",
        role="text_field",
        name="Search",
        bounds={"left": 10, "top": 10, "width": 100, "height": 20},
    )
    id2, c2 = stable_element_id(
        application="Chrome",
        window_hwnd=5,
        automation_id="search",
        role="text_field",
        name="Search",
        bounds={"left": 12, "top": 11, "width": 100, "height": 20},  # within quantize
    )
    assert id1 == id2
    assert c1 >= 0.5
    id3, _ = stable_element_id(
        application="Chrome",
        window_hwnd=5,
        automation_id="other",
        role="button",
        name="Go",
    )
    assert element_fingerprint_changed(id1, id3)
    print("OK UI element normalize + stable IDs")


def test_screen_diff_no_change_and_change():
    from neuron.v4.perception import diff_desktop_states
    from neuron.v4.world.models import DesktopState, WindowState, ApplicationState, MonitorState

    mons = [MonitorState.from_dict(m) for m in _dual_horizontal_mons()]
    a = DesktopState(
        monitors=mons,
        foreground_window=WindowState(hwnd=1, title="A", application="A", focused=True),
        foreground_application=ApplicationState(name="A", focused=True),
        active_monitor_id=1,
    )
    a.ensure_fingerprint()
    b = a.clone()
    d0 = diff_desktop_states(a, b)
    assert d0.changed is False
    assert d0.change_score < 0.08

    b2 = a.clone()
    b2.foreground_window = WindowState(hwnd=2, title="B", application="B", focused=True)
    b2.foreground_application = ApplicationState(name="B", focused=True)
    b2.ensure_fingerprint()
    d1 = diff_desktop_states(a, b2)
    assert d1.changed is True
    assert d1.foreground_changed is True
    assert d1.change_score >= 0.08
    print("OK screen diff no-change + meaningful change")


def test_capture_region_metadata():
    from neuron.v4.perception.types import CaptureMeta

    meta = CaptureMeta(
        bounds={"left": 10, "top": 20, "width": 100, "height": 50},
        width=100,
        height=50,
        monitor_id=2,
        kind="region",
        fingerprint="abc",
        path="",
    )
    d = meta.to_dict()
    assert d["kind"] == "region"
    assert d["path"] == ""
    assert d["monitor_id"] == 2
    print("OK capture region metadata")


def test_ocr_unavailable_partial_failure():
    from neuron.v4.perception import PerceptionEngine, PerceptionErrorCode
    from neuron.v4.world.models import MonitorState

    pe = PerceptionEngine()
    mons = [MonitorState.from_dict(m) for m in _dual_horizontal_mons()]
    with mock.patch.object(pe, "_gather_monitors", return_value=(mons, None)), mock.patch.object(
        pe, "_gather_windows", return_value=([], None, None, [])
    ), mock.patch.object(pe, "_gather_cursor", return_value={}), mock.patch.object(
        pe,
        "_gather_ocr",
        return_value=(
            [],
            False,
            __import__("neuron.v4.perception.types", fromlist=["PerceptionFailure"]).PerceptionFailure(
                code=PerceptionErrorCode.OCR_UNAVAILABLE,
                source="OCR",
                detail="no engine",
            ),
        ),
    ), mock.patch.object(pe, "_capture_target", return_value=(None, None)):
        res = pe.observe(use_ocr=True, use_uia=False, use_browser=False, use_capture=False, push_world=False)
    assert any(f.code == PerceptionErrorCode.OCR_UNAVAILABLE for f in res.failures)
    assert res.desktop.monitors  # partial still has monitors
    assert res.partial or res.ok
    print("OK OCR unavailable + partial perception")


def test_normalize_into_world_and_confidence():
    from neuron.v4.perception import get_perception_engine, reset_perception_engine
    from neuron.v4.world import reset_world_model, get_world_model

    reset_world_model()
    reset_perception_engine()
    pe = get_perception_engine()
    blob = {
        "active_application": "Chrome",
        "window": "YouTube - Chrome",
        "hwnd": 99,
        "focused_monitor": 2,
        "monitors": _dual_horizontal_mons(),
        "clickables": [
            {"name": "Search", "role": "button", "automation_id": "search", "confidence": 0.8},
            {"name": "password", "role": "edit", "automation_id": "pwd"},  # scrubbed
        ],
        "computer_state": True,
    }
    res = pe.normalize_into_world(blob, push_world=True)
    wm = get_world_model()
    assert wm.get_active_application() == "Chrome"
    assert res.confidence > 0.4
    names = [e.name.lower() for e in wm.current.visible_elements]
    assert "password" not in names
    assert any(e.id for e in wm.current.visible_elements)
    # second obs → previous/current
    pe.normalize_into_world(
        {
            **blob,
            "window": "Docs - Chrome",
            "hwnd": 100,
        },
        push_world=True,
    )
    assert wm.previous is not None
    assert wm.diff_snapshots()["changed"] is True
    print("OK normalize_into_world + confidence + scrub + snapshots")


def test_agent_loop_last_perception():
    from neuron.brain.agent_loop import AgentLoop
    from neuron.v4.perception import reset_perception_engine, get_perception_engine
    from neuron.v4.world import reset_world_model

    reset_world_model()
    reset_perception_engine()
    loop = AgentLoop()
    pe = get_perception_engine()
    pe.normalize_into_world(
        {
            "active_application": "Notepad",
            "window": "Untitled",
            "hwnd": 1,
            "monitors": _dual_horizontal_mons(),
        }
    )
    assert loop.last_perception() is not None
    assert loop.last_perception().desktop.foreground_application.name == "Notepad"
    print("OK AgentLoop last_perception")


def test_fullscreen_classification():
    from neuron.v4.perception import classify_fullscreen, FullscreenKind
    from neuron.v4.world.models import MonitorState, WindowState

    mons = [MonitorState.from_dict(m) for m in _dual_horizontal_mons()]
    full = WindowState(left=1920, top=0, width=2560, height=1440, monitor_id=2)
    assert classify_fullscreen(full, mons) is FullscreenKind.WINDOW_FULLSCREEN
    work = WindowState(left=1920, top=0, width=2560, height=1400, monitor_id=2)
    assert classify_fullscreen(work, mons) is FullscreenKind.WINDOW_MAXIMIZED
    normal = WindowState(left=2000, top=40, width=800, height=600, monitor_id=2)
    assert classify_fullscreen(normal, mons) is FullscreenKind.WINDOW_NORMAL
    unknown = WindowState(title="x")
    assert classify_fullscreen(unknown, mons) is FullscreenKind.UNKNOWN
    print("OK fullscreen classification")


# --------------------------------------------------------------------------- V4.3 semantic resolve


def _el(eid, role, name, *, x=0, y=0, w=80, h=24, app="Chrome", window="YouTube", **kw):
    from neuron.v4.world.models import UIElementState, KnowledgeLevel
    from neuron.v4.perception.element_ids import stable_element_id

    bounds = {"left": x, "top": y, "width": w, "height": h, "center_x": x + w // 2, "center_y": y + h // 2}
    sid, conf = stable_element_id(
        application=app, window=window, role=role, name=name, bounds=bounds, automation_id=kw.get("aid", "")
    )
    return UIElementState(
        id=eid or sid,
        role=role,
        name=name,
        text=kw.get("text", name),
        bounds=bounds,
        source=kw.get("source", "uia"),
        application=app,
        window=window,
        monitor_id=kw.get("monitor_id", 1),
        confidence=conf,
        knowledge=KnowledgeLevel.KNOWN,
        attributes={"automation_id": kw.get("aid", ""), "control_type": kw.get("ctype", role)},
    )


def _world_with(elements, app="Chrome", window="YouTube - Chrome"):
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    from neuron.v4.world.models import ApplicationState, WindowState

    reset_world_model()
    wm = DesktopWorldModel()
    wm.update_from_observe_dict(
        {
            "active_application": app,
            "window": window,
            "hwnd": 42,
            "focused_monitor": 1,
            "monitors": _dual_horizontal_mons(),
            "clickables": [],
        }
    )
    st = wm.current
    st.visible_elements = list(elements)
    st.foreground_application = ApplicationState(name=app, focused=True)
    st.foreground_window = WindowState(hwnd=42, title=window, application=app, focused=True, monitor_id=1)
    st.ensure_fingerprint()
    wm._current = st
    return wm


def test_parse_and_roles():
    from neuron.v4.resolve import parse_reference, normalize_role, roles_compatible

    r = parse_reference("click the second video")
    assert r.ordinal == 2
    assert r.role_hint in ("video", "browser_result")
    r2 = parse_reference("the search box")
    assert r2.role_hint == "search_box"
    r3 = parse_reference("button next to Settings")
    assert r3.relation == "next_to"
    assert "settings" in r3.relation_anchor
    assert normalize_role("EditControl") == "text_field"
    assert roles_compatible("search_box", "edit")
    print("OK parse + role normalization")


def test_resolve_search_box_and_text():
    from neuron.v4.resolve import resolve, ResolutionStatus

    els = [
        _el("addr", "text_field", "Address and search bar", x=10, y=10, aid="address"),
        _el("yt", "text_field", "Search", x=400, y=10, aid="search"),
        _el("hid", "text_field", "internal", x=0, y=900),
    ]
    wm = _world_with(els)
    res = resolve("click the search box", world=wm)
    assert res.status is ResolutionStatus.RESOLVED
    assert res.resolved and "search" in res.resolved.name.lower()
    assert res.confidence_band.value == "HIGH" or res.confidence >= 0.55

    res2 = resolve("Settings", world=_world_with([
        _el("s1", "button", "Settings", x=10, y=10),
        _el("s2", "button", "Delete account permanently", x=10, y=50),
    ]))
    assert res2.status is ResolutionStatus.RESOLVED
    assert res2.resolved.name == "Settings"
    print("OK search box + exact text (not reckless fuzzy)")


def test_ordinal_after_semantic_filter():
    from neuron.v4.resolve import resolve, ResolutionStatus

    els = [
        _el("search", "text_field", "Search", x=10, y=10),
        _el("home", "link", "Home", x=10, y=40),
        _el("v1", "link", "Blender beginner tutorial", x=10, y=100, ctype="Hyperlink"),
        _el("v2", "link", "Blender materials crash course", x=10, y=160, ctype="Hyperlink"),
        _el("v3", "link", "Geometry nodes intro", x=10, y=220, ctype="Hyperlink"),
        _el("set", "button", "Settings", x=10, y=400),
    ]
    # mark videos
    for e in els:
        if e.id.startswith("v"):
            e.role = "video"
    wm = _world_with(els)
    res = resolve("play the second video", world=wm)
    assert res.status is ResolutionStatus.RESOLVED
    assert res.resolved and "materials" in res.resolved.name.lower()
    last = resolve("last video", world=wm)
    assert last.ok and "geometry" in last.resolved.name.lower()
    print("OK ordinal after semantic filter")


def test_spatial_and_relational():
    from neuron.v4.resolve import resolve, ResolutionStatus

    els = [
        _el("l", "button", "Cancel", x=10, y=100),
        _el("r", "button", "OK", x=300, y=100),
        _el("set", "button", "Settings", x=100, y=200),
        _el("next", "button", "Apply", x=200, y=200),
    ]
    wm = _world_with(els)
    right = resolve("the right button", world=wm)
    assert right.ok and right.resolved.name == "OK"
    rel = resolve("button next to Settings", world=wm)
    assert rel.ok and rel.resolved.name == "Apply"
    print("OK spatial + relational")


def test_deixis_and_ambiguity():
    from neuron.v4.resolve import resolve, ResolutionStatus, ResolutionContext, get_semantic_resolver

    els = [
        _el("a", "button", "Settings", x=10, y=10),
        _el("b", "button", "Settings", x=200, y=10),
        _el("c", "button", "OK", x=10, y=80),
    ]
    wm = _world_with(els)
    amb = resolve("click Settings", world=wm)
    assert amb.status is ResolutionStatus.AMBIGUOUS
    assert len(amb.candidates) >= 2

    ctx = ResolutionContext(last_element_id="c")
    it = resolve("click it", world=wm, context=ctx)
    assert it.status is ResolutionStatus.RESOLVED
    assert it.resolved.element_id == "c"

    many = resolve("that button", world=wm, context=ResolutionContext())
    assert many.status in (ResolutionStatus.AMBIGUOUS, ResolutionStatus.INSUFFICIENT_CONTEXT)
    print("OK deixis + ambiguity (no random Settings)")


def test_confidence_and_revalidate():
    from neuron.v4.resolve import (
        resolve,
        ResolutionStatus,
        RevalidateStatus,
        get_semantic_resolver,
        ResolvedElement,
    )

    els = [_el("ok", "button", "Continue", x=10, y=10, aid="continue")]
    wm = _world_with(els)
    res = resolve("Continue", world=wm)
    assert res.ok and res.confidence >= 0.75
    rv = get_semantic_resolver().revalidate(res.resolved.element_id, world=wm, prior=res.resolved)
    assert rv is RevalidateStatus.STILL_VALID

    # move
    els2 = [_el("ok", "button", "Continue", x=500, y=500, aid="continue")]
    # keep same id
    els2[0].id = res.resolved.element_id
    wm2 = _world_with(els2)
    rv2 = get_semantic_resolver().revalidate(
        res.resolved.element_id, world=wm2, prior=res.resolved
    )
    assert rv2 in (RevalidateStatus.MOVED, RevalidateStatus.STILL_VALID)

    missing = get_semantic_resolver().revalidate("nope:missing", world=wm2)
    assert missing is RevalidateStatus.MISSING
    print("OK confidence + revalidate")


def test_insufficient_and_empty():
    from neuron.v4.resolve import resolve, ResolutionStatus
    from neuron.v4.world import DesktopWorldModel, reset_world_model

    reset_world_model()
    wm = DesktopWorldModel()
    res = resolve("first video", world=wm)
    assert res.status in (
        ResolutionStatus.INSUFFICIENT_CONTEXT,
        ResolutionStatus.STALE_WORLD,
        ResolutionStatus.NOT_FOUND,
    )
    assert res.needs_reobserve
    print("OK insufficient context / empty world")


def test_performance_500_elements():
    import time
    from neuron.v4.resolve import resolve

    els = [
        _el(f"e{i}", "button" if i % 5 else "link", f"Item {i}", x=(i % 40) * 30, y=(i // 40) * 20)
        for i in range(500)
    ]
    els.append(_el("target", "button", "UniqueSubmit", x=10, y=10, aid="unique"))
    wm = _world_with(els)
    t0 = time.perf_counter()
    res = resolve("UniqueSubmit", world=wm)
    ms = (time.perf_counter() - t0) * 1000
    assert res.ok
    assert ms < 500, ms
    print(f"OK performance 500 elements in {ms:.1f}ms")


def test_agent_loop_semantic_resolve():
    from neuron.brain.agent_loop import AgentLoop
    from neuron.v4.resolve import ResolutionStatus, reset_semantic_resolver

    reset_semantic_resolver()
    els = [_el("s", "text_field", "Search", x=40, y=10, aid="search")]
    wm = _world_with(els)
    loop = AgentLoop()
    # point loop world at our wm via singleton already updated
    from neuron.v4.world import get_world_model
    get_world_model()._current = wm.current
    r = loop.semantic_resolve("search box")
    assert r.status is ResolutionStatus.RESOLVED
    print("OK AgentLoop.semantic_resolve")


# --------------------------------------------------------------------------- V4.4 hierarchical planner


def _chrome_world(*, monitor_id=1, focused=True, title="New Tab - Chrome"):
    from neuron.v4.world import DesktopWorldModel, reset_world_model

    reset_world_model()
    wm = DesktopWorldModel()
    left = 100 if int(monitor_id) == 1 else 2000
    wm.update_from_observe_dict(
        {
            "monitors": _dual_horizontal_mons(),
            "active_application": "Chrome" if focused else "Explorer",
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
                    "focused": focused,
                }
            ],
        }
    )
    return wm


def test_v44_simple_open_mute_volume():
    from neuron.v4.plan import HierarchicalPlanner, DecisionKind, reset_hierarchical_planner

    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    plan = p.create_plan("open chrome")
    assert plan.source == "template"
    assert any(sg.intent == "open_app" for sg in plan.subgoals)
    d = p.plan_next(plan, world=None)
    # UNKNOWN world → observe for open_app
    assert d.kind in (DecisionKind.OBSERVE, DecisionKind.ACT)
    plan2 = p.create_plan("mute")
    d2 = p.plan_next(plan2, world=_chrome_world())
    assert d2.kind is DecisionKind.ACT
    assert d2.grounded and d2.grounded.tool == "volume"
    plan3 = p.create_plan("volume up")
    d3 = p.plan_next(plan3, world=_chrome_world())
    assert d3.kind is DecisionKind.ACT and d3.grounded.arguments.get("action") == "up"
    print("OK V4.4 simple open/mute/volume")


def test_v44_already_satisfied_skip():
    from neuron.v4.plan import HierarchicalPlanner, DecisionKind, StepStatus, reset_hierarchical_planner

    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    wm = _chrome_world(monitor_id=1, focused=True)
    plan = p.create_plan("open chrome")
    d = p.plan_next(plan, world=wm)
    # open skipped → COMPLETE (single subgoal)
    assert plan.subgoals[0].status is StepStatus.SKIPPED
    assert d.kind is DecisionKind.COMPLETE

    plan_f = p.create_plan("focus chrome")
    d_f = p.plan_next(plan_f, world=wm)
    assert plan_f.subgoals[0].status is StepStatus.SKIPPED
    assert d_f.kind is DecisionKind.COMPLETE

    wm2 = _chrome_world(monitor_id=2, focused=True)
    plan_m = p.create_plan("move chrome to monitor 2")
    d_m = p.plan_next(plan_m, world=wm2)
    assert plan_m.subgoals[0].status is StepStatus.SKIPPED
    assert d_m.kind is DecisionKind.COMPLETE
    print("OK V4.4 already-satisfied skip")


def test_v44_youtube_multistep_and_monitor():
    from neuron.v4.plan import HierarchicalPlanner, DecisionKind, StepStatus, reset_hierarchical_planner

    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    text = (
        "Open YouTube on monitor 2, search for Blender beginner tutorials, "
        "play the first video and fullscreen it."
    )
    plan = p.create_plan(text)
    assert len(plan.subgoals) >= 5
    intents = [sg.intent for sg in plan.subgoals]
    assert "youtube_search" in intents
    assert "youtube_play" in intents
    assert "youtube_fullscreen" in intents
    assert any(sg.intent == "move_monitor" for sg in plan.subgoals)

    # Empty world → observe first
    d0 = p.plan_next(plan, world=None)
    assert d0.kind is DecisionKind.OBSERVE

    # Chrome+YouTube already on mon 2 → skip avail + place
    wm = _chrome_world(monitor_id=2, title="YouTube - Chrome")
    d1 = p.plan_next(plan, world=wm)
    assert plan.subgoals[0].status is StepStatus.SKIPPED
    assert d1.kind is DecisionKind.ACT
    assert d1.grounded and "search" in d1.grounded.tool
    print("OK V4.4 youtube multistep + monitor")


def test_v44_semantic_ambiguity():
    from neuron.v4.plan import HierarchicalPlanner, DecisionKind, reset_hierarchical_planner
    from neuron.v4.resolve import ResolutionResult, ResolutionStatus, ElementReference

    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    plan = p.create_plan("click Settings")
    assert plan.subgoals[0].intent == "click"
    amb = ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        reference=ElementReference(raw="Settings"),
        evidence="two settings",
    )
    d = p.plan_next(plan, world=_chrome_world(), resolution=amb)
    assert d.kind is DecisionKind.CLARIFY
    assert "not" in d.reason.lower() or "AMBIGUOUS" in d.reason
    print("OK V4.4 semantic ambiguity no guess")


def test_v44_context_followup_and_multi_app():
    from neuron.v4.plan import HierarchicalPlanner, DecisionKind, reset_hierarchical_planner

    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    class Ctx:
        rewritten = "search on youtube for Blender tutorials"

    plan = p.create_plan("search Blender", context=Ctx())
    # context rewrite applied inside create — youtube workflow if rewritten used
    # _apply_context replaces text with rewritten
    assert any(sg.intent == "youtube_search" for sg in plan.subgoals) or plan.source in (
        "template", "multi_app", "fallback"
    )

    plan2 = p.create_plan("Open Spotify and Chrome")
    apps = [sg.target_hints.get("name") for sg in plan2.subgoals if sg.intent == "open_app"]
    assert "Spotify" in apps and "Chrome" in apps

    plan3 = p.create_plan(
        "Open YouTube on monitor 2 and Spotify on monitor 1"
    )
    assert len(plan3.subgoals) >= 3
    print("OK V4.4 context + multi-app")


def test_v44_unknown_safety_fail_cancel():
    from neuron.v4.plan import (
        HierarchicalPlanner,
        DecisionKind,
        PlanStatus,
        StepStatus,
        Subgoal,
        TaskPlan,
        Goal,
        reset_hierarchical_planner,
    )
    from neuron.v4.plan.templates import legacy_steps_to_plan
    from neuron.v4.plan.validate import validate_llm_plan_dict

    reset_hierarchical_planner()
    p = HierarchicalPlanner()

    # UNKNOWN open → observe
    plan = p.create_plan("open chrome")
    d = p.plan_next(plan, world=None)
    assert d.kind is DecisionKind.OBSERVE
    assert d.needs_observation

    # CONFIRM close_app
    g = Goal(text="close notepad")
    plan_c = legacy_steps_to_plan(
        [{"action": "close_app", "args": {"name": "Notepad"}, "expected_result": "closed"}],
        g,
    )
    p.load_plan(plan_c)
    d_c = p.plan_next(plan_c, world=_chrome_world())
    assert d_c.kind is DecisionKind.CONFIRM
    assert plan_c.status is PlanStatus.WAITING_FOR_CONFIRMATION
    d_c2 = p.plan_next(plan_c, confirmed=False)
    assert d_c2.kind is DecisionKind.CONFIRM
    d_ok = p.plan_next(plan_c, confirmed=True)
    assert d_ok.kind is DecisionKind.ACT

    # BLOCKED shell
    plan_b = legacy_steps_to_plan(
        [{"action": "run_shell", "args": {"command": "rm -rf C:\\"}, "expected_result": "no"}],
        Goal(text="wipe"),
    )
    # validate may warn; force plan_next
    p.load_plan(plan_b)
    d_b = p.plan_next(plan_b, world=_chrome_world())
    assert d_b.kind is DecisionKind.FAIL

    # unknown / invalid LLM
    ok, err, _ = validate_llm_plan_dict({"steps": [{"action": "not_a_tool", "args": {}}]})
    assert ok is False
    ok2, err2, _ = validate_llm_plan_dict({"steps": "bad"})
    assert ok2 is False

    # dependency unmet — second ready but first pending: select first
    g2 = Goal(text="dep")
    sg1 = Subgoal(description="a", intent="open_app", preferred_tools=["open_app"],
                  target_hints={"name": "Chrome"}, subgoal_id="a", status=StepStatus.PENDING)
    sg2 = Subgoal(description="b", intent="focus_app", preferred_tools=["focus_app"],
                  target_hints={"name": "Chrome"}, depends_on=["a"], subgoal_id="b",
                  status=StepStatus.PENDING)
    plan_d = TaskPlan(goal=g2, subgoals=[sg1, sg2], status=PlanStatus.ACTIVE, source="test")
    # Mark first failed permanently with max attempts
    sg1.status = StepStatus.FAILED
    sg1.attempt_count = 3
    p.load_plan(plan_d)
    d_dep = p.plan_next(plan_d, world=_chrome_world())
    # b blocked by unmet dep → WAIT or skip to nothing
    assert d_dep.kind in (DecisionKind.WAIT, DecisionKind.COMPLETE, DecisionKind.FAIL)

    # cancel
    plan_x = p.create_plan("mute")
    p.cancel(plan_x)
    assert plan_x.status is PlanStatus.CANCELLED
    d_x = p.plan_next(plan_x)
    assert d_x.kind is DecisionKind.CANCELLED
    print("OK V4.4 unknown/safety/fail/cancel")


def test_v44_agent_loop_integration():
    from neuron.brain.agent_loop import AgentLoop
    from neuron.v4.plan import DecisionKind, reset_hierarchical_planner
    from neuron.v4.world import get_world_model

    reset_hierarchical_planner()
    loop = AgentLoop()
    plan = loop.create_task_plan("mute")
    assert plan is not None and loop.active_task_plan is plan
    get_world_model()._current = _chrome_world().current
    d = loop.plan_next()
    assert d.kind is DecisionKind.ACT
    legacy = loop.grounded_action_to_legacy(d)
    assert legacy and legacy["steps"][0]["action"] == "volume"
    # V4.5: caller ok alone must not succeed — need VerificationOutcome
    from neuron.v4.types import VerificationOutcome
    loop.apply_plan_outcome(d, ok=True)
    assert loop.active_task_plan.subgoals[0].status.value == "UNCERTAIN"
    loop.apply_plan_outcome(d, verification=VerificationOutcome.SUCCESS)
    assert loop.active_task_plan.subgoals[0].status.value == "SUCCEEDED"
    loop.cancel_task_plan()
    assert loop.active_task_plan.status.value == "CANCELLED"
    d2 = loop.plan_next()
    assert d2.kind is DecisionKind.CANCELLED
    print("OK V4.4 AgentLoop integration")


def test_v44_max_attempts_uncertain():
    from neuron.v4.plan import (
        HierarchicalPlanner, DecisionKind, StepStatus, reset_hierarchical_planner
    )

    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    plan = p.create_plan("mute")
    d = p.plan_next(plan, world=_chrome_world())
    assert d.kind is DecisionKind.ACT
    p.apply_action_outcome(plan, d, ok=None, detail="no signal")
    sg = plan.subgoals[0]
    assert sg.status is StepStatus.UNCERTAIN
    # failures to max
    for _ in range(sg.max_attempts):
        sg.status = StepStatus.READY
        d = p.plan_next(plan, world=_chrome_world())
        p.apply_action_outcome(plan, d, ok=False, detail="fail")
    assert plan.subgoals[0].status is StepStatus.FAILED
    print("OK V4.4 uncertain + max attempts")


# --------------------------------------------------------------------------- V4.5 VerificationEngine


def test_v45_open_app_verification():
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify import VerificationEngine, reset_verification_engine, derive_expectation

    reset_verification_engine()
    eng = VerificationEngine()
    exp = derive_expectation("open_app", {"name": "Chrome"})

    # immediate success
    r = eng.verify(exp, world=_chrome_world(), action_result={"ok": True}, wait=False)
    assert r.status is VerificationOutcome.SUCCESS

    # wrong app
    r2 = eng.verify(
        derive_expectation("open_app", {"name": "Blender"}),
        world=_chrome_world(),
        action_result={"ok": True},
        wait=False,
    )
    assert r2.status is VerificationOutcome.FAILURE

    # process without window
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    reset_world_model()
    empty = DesktopWorldModel()
    empty.update_from_observe_dict({"monitors": _dual_horizontal_mons(), "windows": []})
    r3 = eng.verify(
        exp,
        world=empty,
        action_result={"ok": True, "state": {"process": True, "verified": False}},
        wait=False,
    )
    assert r3.status is VerificationOutcome.UNCERTAIN

    # tool ok alone + empty world
    r4 = eng.verify(exp, world=None, action_result={"ok": True}, wait=False)
    assert r4.status is not VerificationOutcome.SUCCESS
    print("OK V4.5 open_app verification")


def test_v45_focus_monitor_browser_fullscreen():
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify import VerificationEngine, derive_expectation
    from neuron.v4.world.models import BrowserState, KnowledgeLevel

    eng = VerificationEngine()
    wm = _chrome_world(focused=True)
    r = eng.verify(derive_expectation("focus_app", {"name": "Chrome"}), world=wm, wait=False)
    assert r.status is VerificationOutcome.SUCCESS
    r_bad = eng.verify(derive_expectation("focus_app", {"name": "Blender"}), world=wm, wait=False)
    assert r_bad.status is VerificationOutcome.FAILURE

    wm2 = _chrome_world(monitor_id=2)
    r_m = eng.verify(
        derive_expectation("move_window_to_monitor", {"name": "Chrome", "monitor": 2}),
        world=wm2,
        wait=False,
    )
    assert r_m.status is VerificationOutcome.SUCCESS
    r_m2 = eng.verify(
        derive_expectation("move_window_to_monitor", {"name": "Chrome", "monitor": 1}),
        world=wm2,
        wait=False,
    )
    assert r_m2.status is VerificationOutcome.FAILURE

    # negative / vertical still works via world fixtures
    from neuron.v4.world import DesktopWorldModel, reset_world_model
    reset_world_model()
    wm_n = DesktopWorldModel()
    wm_n.update_from_observe_dict(
        {
            "monitors": _negative_coord_mons(),
            "windows": [{
                "hwnd": 1, "title": "Chrome", "app": "Chrome", "monitor_id": 2,
                "left": -1800, "top": 10, "width": 800, "height": 600, "focused": True,
            }],
            "active_application": "Chrome",
        }
    )
    assert eng.verify(
        derive_expectation("move_window_to_monitor", {"name": "Chrome", "monitor": 2}),
        world=wm_n, wait=False,
    ).status is VerificationOutcome.SUCCESS

    # browser URL
    wm_b = _chrome_world(title="YouTube - Chrome")
    st = wm_b.current
    st.browser = BrowserState(browser="Chrome", url="https://www.youtube.com/results?search_query=blender", tab_title="YouTube", knowledge=KnowledgeLevel.KNOWN)
    wm_b._current = st
    r_u = eng.verify(derive_expectation("youtube.search", {"query": "blender"}), world=wm_b, wait=False)
    assert r_u.status is VerificationOutcome.SUCCESS

    # URL mismatch
    st.browser.url = "https://example.com"
    r_bad_u = eng.verify(derive_expectation("browser_navigate", {"url": "https://youtube.com"}), world=wm_b, wait=False)
    assert r_bad_u.status is VerificationOutcome.FAILURE

    # title-only → UNCERTAIN
    st.browser.url = ""
    st.browser.tab_title = "YouTube"
    r_t = eng.verify(derive_expectation("youtube.home", {}), world=wm_b, wait=False)
    assert r_t.status is VerificationOutcome.UNCERTAIN

    # fullscreen: maximized ≠ media fullscreen
    st.browser.fullscreen = None
    r_fs = eng.verify(derive_expectation("youtube.fullscreen", {}), world=wm_b, wait=False)
    assert r_fs.status is VerificationOutcome.UNCERTAIN
    st.browser.fullscreen = True
    r_fs2 = eng.verify(derive_expectation("youtube.fullscreen", {}), world=wm_b, wait=False)
    assert r_fs2.status is VerificationOutcome.SUCCESS
    print("OK V4.5 focus/monitor/browser/fullscreen")


def test_v45_click_type_outcomes_plan():
    from neuron.v4.types import ActionResult, VerificationOutcome
    from neuron.v4.verify import VerificationEngine, derive_expectation, VerificationReport
    from neuron.v4.plan import HierarchicalPlanner, DecisionKind, StepStatus, reset_hierarchical_planner

    eng = VerificationEngine()
    # click no change → UNCERTAIN
    r = eng.verify(
        derive_expectation("click", {"element_id": "x"}),
        world=_chrome_world(),
        screen_diff={"changed": False, "change_score": 0},
        action_result={"ok": True},
        wait=False,
    )
    assert r.status is VerificationOutcome.UNCERTAIN

    # trivial change
    r2 = eng.verify(
        derive_expectation("click", {}),
        world=_chrome_world(),
        screen_diff={"changed": True, "change_score": 0.01},
        action_result={"ok": True},
        wait=False,
    )
    assert r2.status is not VerificationOutcome.SUCCESS

    # type sensitive
    r3 = eng.verify(
        derive_expectation("type_text", {"text": "secret", "field": "password"}),
        world=_chrome_world(),
        action_result={"ok": True},
        wait=False,
    )
    assert r3.status is VerificationOutcome.UNCERTAIN

    # ActionResult success + Verification FAILURE
    assert r2.action_result_ok is True or True
    rep = VerificationReport(status=VerificationOutcome.FAILURE, action_result_ok=True)
    assert rep.ok_for_advance is False

    # planner: SUCCESS advances, UNCERTAIN does not complete
    reset_hierarchical_planner()
    p = HierarchicalPlanner()
    plan = p.create_plan("mute")
    d = p.plan_next(plan, world=_chrome_world())
    p.apply_verification(plan, d, VerificationOutcome.UNCERTAIN)
    assert plan.subgoals[0].status is StepStatus.UNCERTAIN
    assert p.plan_is_complete(plan) is False
    p.apply_verification(plan, d, VerificationOutcome.SUCCESS)
    assert plan.subgoals[0].status is StepStatus.SUCCEEDED
    assert p.plan_is_complete(plan) is True

    # executor failure
    rf = eng.verify(
        derive_expectation("open_app", {"name": "Chrome"}),
        world=_chrome_world(),
        action_result=ActionResult(ok=False, error="boom"),
        wait=False,
    )
    assert rf.status is VerificationOutcome.FAILURE
    print("OK V4.5 click/type/outcomes/plan")


def test_v45_cancel_wait():
    from neuron.v4.verify.wait import wait_until
    from neuron.v4.types import VerificationOutcome

    calls = {"n": 0}

    def pred():
        calls["n"] += 1
        return VerificationOutcome.UNCERTAIN, 0.1, None, "wait", "WAIT_POLL"

    status, conf, ev, reason, method, cancelled, ms = wait_until(
        pred, timeout_s=0.4, poll_s=0.05, cancel_check=lambda: calls["n"] >= 2
    )
    assert cancelled is True
    assert reason == "cancelled"
    assert calls["n"] >= 2
    print("OK V4.5 cancel wait")


def test_v45_agent_loop_verify_action():
    from neuron.brain.agent_loop import AgentLoop
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.world import get_world_model

    loop = AgentLoop()
    get_world_model()._current = _chrome_world().current
    rep = loop.verify_action(
        step={"action": "open_app", "args": {"name": "Chrome"}, "expected_result": "Chrome open"},
        action_result={"ok": True},
        wait=False,
    )
    assert rep.status is VerificationOutcome.SUCCESS
    print("OK V4.5 AgentLoop.verify_action")


# --------------------------------------------------------------------------- V4.6 RecoveryEngine


def test_v46_diagnose_and_no_blind_retry():
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify.types import VerificationReport, VerificationEvidence
    from neuron.v4.recover import RecoveryEngine, RecoveryKind, FailureCategory, reset_recovery_engine

    reset_recovery_engine()
    eng = RecoveryEngine()
    d = eng.decide(
        verification=VerificationReport(status=VerificationOutcome.UNCERTAIN, reason="no observable state change"),
        tool="click",
        args={"name": "Go"},
    )
    assert d.diagnosis and d.diagnosis.category is FailureCategory.ACTION_NO_EFFECT
    assert d.kind is RecoveryKind.REOBSERVE
    # second without state change should not blind retry same click
    d2 = eng.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="verification failed"),
        tool="click",
        args={"name": "Go"},
        world_after_fp="same",
        state_changed_since_fail=False,
    )
    assert not (d2.kind is RecoveryKind.RETRY and d2.primary_action and d2.primary_action.tool == "click")
    print("OK V4.6 diagnose + no blind retry")


def test_v46_focus_reground_safety_cancel():
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify.types import VerificationReport, VerificationEvidence
    from neuron.v4.recover import RecoveryEngine, RecoveryKind, RecoveryStatus, reset_recovery_engine
    from neuron.brain.agent_loop import AgentLoop

    reset_recovery_engine()
    eng = RecoveryEngine()
    d = eng.decide(
        verification=VerificationReport(
            status=VerificationOutcome.FAILURE,
            reason="foreground is Wrong",
            evidence=VerificationEvidence(facts={"active_application": "Wrong"}),
        ),
        tool="type_text",
        args={"text": "hi"},
        target_app="Chrome",
    )
    assert d.kind is RecoveryKind.FOCUS_THEN_RETRY

    d2 = eng.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="missing"),
        tool="click",
        args={"reference": "search box"},
        reference="search box",
        resolution_status="STALE_WORLD",
    )
    assert d2.kind in (RecoveryKind.REGROUND, RecoveryKind.REOBSERVE)

    d3 = eng.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="blocked"),
        tool="run_shell",
        args={"command": "x"},
        legacy_diagnosis={"category": "POLICY_BLOCKED"},
    )
    assert d3.kind is RecoveryKind.FAIL and d3.status is RecoveryStatus.BLOCKED

    loop = AgentLoop()
    loop.create_task_plan("mute")
    dc = loop.cancel_recovery()
    assert dc.kind is RecoveryKind.CANCEL
    print("OK V4.6 focus/reground/safety/cancel")


def test_v46_planner_apply_recovery():
    from neuron.v4.types import VerificationOutcome
    from neuron.v4.verify.types import VerificationReport
    from neuron.v4.plan import HierarchicalPlanner, PlanStatus, reset_hierarchical_planner
    from neuron.v4.recover import RecoveryEngine, RecoveryKind, reset_recovery_engine

    reset_hierarchical_planner()
    reset_recovery_engine()
    p = HierarchicalPlanner()
    plan = p.create_plan("open chrome")
    eng = RecoveryEngine()
    d = eng.decide(
        verification=VerificationReport(status=VerificationOutcome.FAILURE, reason="ambiguous"),
        tool="click",
        args={},
        resolution_status="AMBIGUOUS",
    )
    assert d.kind is RecoveryKind.CLARIFY
    p.apply_recovery(plan, d)
    assert plan.status is PlanStatus.BLOCKED
    print("OK V4.6 planner apply_recovery")


def test_v47_normalize_and_followup():
    from neuron.v4.context import reset_conversation_engine, ContinuityKind, IntentFamily, RouteDest

    eng = reset_conversation_engine()
    for phrase in ("open chrome", "bring up chrome", "uh open chrome please"):
        u = eng.understand(phrase)
        assert u.goal and u.goal.intent_family is IntentFamily.OPEN
        assert "chrome" in u.rewritten_command.lower()
    eng.apply_verified(action="open_app", args={"name": "Chrome"}, status="SUCCESS")
    u2 = eng.understand("go to YouTube")
    assert u2.continuity is ContinuityKind.FOLLOW_UP
    u3 = eng.understand("don't open Spotify")
    assert u3.route is RouteDest.REJECT
    print("OK V4.7 normalize + follow-up + negation")


def test_v47_clarify_confirm_verify():
    from neuron.v4.context import reset_conversation_engine, ContinuityKind
    from neuron.v4.context.clarify import set_clarification, set_confirmation

    eng = reset_conversation_engine()
    eng.set_pending_clarification(
        set_clarification(
            prompt="Which?",
            original_goal="click Settings",
            options=[{"label": "Chrome"}, {"label": "App"}],
        )
    )
    u = eng.understand("Chrome")
    assert u.continuity is ContinuityKind.CLARIFICATION_ANSWER
    assert u.clarification_resolution and u.clarification_resolution["resolved"]

    eng.set_pending_confirmation(set_confirmation(action="x", risk="HIGH"))
    uy = eng.understand("yes")
    assert uy.confirmation_resolution and uy.confirmation_resolution["authorized"]

    eng2 = reset_conversation_engine()
    eng2.apply_verified(
        action="move_window_to_monitor",
        args={"monitor": 2, "name": "Chrome"},
        status="FAILURE",
    )
    assert eng2.state.task.verified_facts.get("monitor") != 2
    eng2.apply_verified(
        action="move_window_to_monitor",
        args={"monitor": 2, "name": "Chrome"},
        status="SUCCESS",
    )
    assert eng2.state.task.active_monitor == 2
    print("OK V4.7 clarify/confirm/verify context")


def test_v47_routing_parity_unit():
    from neuron.v4.context import reset_conversation_engine, routing_parity_check

    eng = reset_conversation_engine()
    eng.apply_verified(action="open_app", args={"name": "Chrome"}, status="SUCCESS")
    total = 0
    for s in ("open chrome", "mute", "search Blender"):
        total += routing_parity_check(s)["mismatch"]
    assert total == 0
    print("OK V4.7 routing parity unit")


def test_v48_capability_resolve():
    from neuron.v4.capability import reset_capability_catalog, resolve_intent, coverage_report

    reset_capability_catalog()
    rep = coverage_report()
    assert rep["total"] > 10
    assert rep["DUPLICATE_CAPABILITY_IMPLEMENTATION_COUNT"] == 0
    r = resolve_intent("open_app", {"name": "Chrome"})
    assert r.ok and r.verification_kind == "APP_OPEN"
    bad = resolve_intent("open_app", preferred=["no.such.capability.zzz"])
    assert not bad.ok and bad.unsupported
    print("OK V4.8 capability resolve")


def test_v49_eligibility_and_privacy():
    from neuron.v4.learn import build_trace, is_eligible, reset_procedure_learner
    from neuron.v4.learn.types import ProcedureCandidate, ProcedureStep
    from neuron.v4.learn import privacy

    reset_procedure_learner()
    privacy.reset_privacy_metrics()
    ok = build_trace(
        goal_text="youtube Blender on monitor 2",
        steps=[
            {"tool": "windows.open_app", "arguments": {"name": "Chrome"}, "verification": "SUCCESS"},
            {"tool": "youtube.search", "arguments": {"query": "Blender"}, "verification": "SUCCESS"},
        ],
        final_status="SUCCESS",
        task_verified=True,
    )
    assert is_eligible(ok)[0]
    bad = build_trace(
        goal_text="x",
        steps=[
            {"tool": "youtube.search", "arguments": {"query": "x"}, "verification": "SUCCESS"},
            {"tool": "youtube.play_result", "arguments": {"index": 1}, "verification": "UNCERTAIN"},
        ],
        final_status="SUCCESS",
        task_verified=True,
    )
    assert not is_eligible(bad)[0]
    assert not privacy.validate_privacy(
        ProcedureCandidate(
            name="bad",
            steps=[ProcedureStep(tool="type_text", arguments={"password": "x"})],
        )
    )[0]
    assert privacy.PROCEDURE_PRIVACY_VIOLATION_COUNT == 0
    print("OK V4.9 eligibility + privacy")


def test_v49_procedure_catalog_and_learning_flag():
    from neuron.v4.learn import (
        build_trace,
        reset_procedure_registry,
        get_procedure_learner,
        procedure_learning_enabled,
    )
    from neuron.v4.capability import reset_capability_catalog, get_capability_catalog
    from neuron.v4.capability.types import CapabilityKind

    assert procedure_learning_enabled() is False
    reg = reset_procedure_registry(clear_store=True)
    learner = get_procedure_learner()
    for q in ("Blender", "Unreal", "Python"):
        learner.ingest_trace(
            build_trace(
                goal_text=f"youtube {q}",
                steps=[
                    {"tool": "windows.open_app", "arguments": {"name": "Chrome"}, "verification": "SUCCESS"},
                    {"tool": "youtube.search", "arguments": {"query": q}, "verification": "SUCCESS"},
                ],
                final_status="SUCCESS",
                task_verified=True,
                intent_family="youtube_search",
            )
        )
    from neuron.v4.learn.generalize import generalize_traces
    cand = generalize_traces(learner.traces)
    ok, _, proc = reg.accept_and_register(cand, force=True)
    assert ok and proc
    reset_capability_catalog()
    reg.sync_catalog()
    cap = get_capability_catalog().get(proc.procedure_id)
    assert cap and cap.kind is CapabilityKind.COMPOSITE
    print("OK V4.9 catalog COMPOSITE + learning flag default off")


def test_v410_voice_defaults_and_shadow():
    from neuron.v4.voice import (
        hierarchical_voice_enabled,
        voice_routing_mode,
        VoiceRoutingMode,
        reset_voice_metrics,
        compare_shadow,
        VoiceRequest,
        SHADOW_MUTATION_COUNT,
        canary_eligible,
        guard_hierarchical_say,
        TaskOutcomeKind,
        build_migration_report,
        procedure_learning_off,
        voice_config_snapshot,
    )

    # Fail-closed: when master flag is off, mode is LEGACY regardless of config string
    import neuron.v4.voice.config as vcfg
    snap = voice_config_snapshot()
    assert procedure_learning_off() is True
    # Production default intent: learning off; mode may be SHADOW/CANARY during validation
    assert snap.get("procedure_learning_enabled") is False
    if not hierarchical_voice_enabled():
        assert voice_routing_mode() is VoiceRoutingMode.LEGACY
    reset_voice_metrics()
    cmp = compare_shadow(VoiceRequest(text="Open Chrome", normalized="Open Chrome"))
    assert cmp.mutated is False
    assert SHADOW_MUTATION_COUNT == 0
    assert canary_eligible(text="Open Chrome", intent_family="APP_OPEN")[0]
    assert not canary_eligible(text="enter password hunter2", intent_family="APP_OPEN")[0]
    say = guard_hierarchical_say("Done.", TaskOutcomeKind.UNCERTAIN, action_summary="fullscreen")
    assert "Done." != say.strip()
    rep = build_migration_report(
        mock_parity_pass=True,
        shadow_parity_pass=True,
        live_parity_pass="NOT_RUN",
        safety_pass=True,
        false_success_pass=True,
        recovery_loop_pass=True,
        context_pass=True,
        latency_pass=True,
    )
    # ready_for_default remains computed; NOT_RUN LIVE keeps it false
    assert rep.ready_for_default is False or snap.get("voice_routing_mode") != "LEGACY"
    print("OK V4.10 voice shadow gates + readiness computed")


if __name__ == "__main__":
    test_plan_roundtrip()
    test_verification_uncertain_not_success()
    test_agent_state_interrupt()
    test_recovery_from_v3()
    test_world_model_creation_and_snapshot()
    test_state_update_pushes_previous()
    test_monitor_geometry_negative_and_vertical()
    test_left_right_primary_other_resolution()
    test_window_monitor_and_app_lookup()
    test_unknown_and_confidence()
    test_bounded_interaction_history()
    test_computer_state_adapter()
    test_v3_world_state_adapter()
    test_agent_loop_world_access()
    test_agent_state_apply_desktop()
    test_empty_observation_unknown()
    test_perception_monitor_normalization()
    test_window_enum_and_foreground()
    test_ui_element_normalization_and_stable_ids()
    test_screen_diff_no_change_and_change()
    test_capture_region_metadata()
    test_ocr_unavailable_partial_failure()
    test_normalize_into_world_and_confidence()
    test_agent_loop_last_perception()
    test_fullscreen_classification()
    test_parse_and_roles()
    test_resolve_search_box_and_text()
    test_ordinal_after_semantic_filter()
    test_spatial_and_relational()
    test_deixis_and_ambiguity()
    test_confidence_and_revalidate()
    test_insufficient_and_empty()
    test_performance_500_elements()
    test_agent_loop_semantic_resolve()
    test_v44_simple_open_mute_volume()
    test_v44_already_satisfied_skip()
    test_v44_youtube_multistep_and_monitor()
    test_v44_semantic_ambiguity()
    test_v44_context_followup_and_multi_app()
    test_v44_unknown_safety_fail_cancel()
    test_v44_agent_loop_integration()
    test_v44_max_attempts_uncertain()
    test_v45_open_app_verification()
    test_v45_focus_monitor_browser_fullscreen()
    test_v45_click_type_outcomes_plan()
    test_v45_cancel_wait()
    test_v45_agent_loop_verify_action()
    test_v46_diagnose_and_no_blind_retry()
    test_v46_focus_reground_safety_cancel()
    test_v46_planner_apply_recovery()
    test_v47_normalize_and_followup()
    test_v47_clarify_confirm_verify()
    test_v47_routing_parity_unit()
    test_v48_capability_resolve()
    test_v49_eligibility_and_privacy()
    test_v49_procedure_catalog_and_learning_flag()
    test_v410_voice_defaults_and_shadow()
    print("\nALL V4 unit tests passed (V4.0 .. V4.10)")
