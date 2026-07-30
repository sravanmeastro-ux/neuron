"""Phase 10 multi-monitor intelligence — geometry, NL refs, move+verify."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fake_mons():
    # Two displays side-by-side — geometry only (no hardcoded "1920 assumes primary")
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
            "label": "#1 main/primary/left 1920x1080 @(0,0)",
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
            "label": "#2 secondary/right/other 2560x1440 @(1920,0)",
        },
    ]


def test_annotate_roles_geometry():
    from neuron.windows import monitors as mon_mod

    raw = [
        {"id": 1, "left": 1920, "top": 0, "width": 1000, "height": 800, "primary": False,
         "work_left": 1920, "work_top": 0, "work_width": 1000, "work_height": 780},
        {"id": 2, "left": 0, "top": 0, "width": 800, "height": 600, "primary": True,
         "work_left": 0, "work_top": 0, "work_width": 800, "work_height": 580},
    ]
    out = mon_mod._annotate_roles(raw)
    by_id = {int(m["id"]): m for m in out}
    assert "left" in by_id[2]["roles"]
    assert "right" in by_id[1]["roles"]
    assert "main" in by_id[2]["roles"]
    assert "other" in by_id[1]["roles"]
    print("OK roles from geometry", by_id[2]["roles"], by_id[1]["roles"])


def test_resolve_nl_refs():
    from neuron.windows import monitors as mon_mod

    mons = _fake_mons()
    assert mon_mod.resolve_monitor_ref("screen 1", monitors=mons)["id"] == 1
    assert mon_mod.resolve_monitor_ref("screen 2", monitors=mons)["id"] == 2
    assert mon_mod.resolve_monitor_ref("left monitor", monitors=mons)["id"] == 1
    assert mon_mod.resolve_monitor_ref("right screen", monitors=mons)["id"] == 2
    assert mon_mod.resolve_monitor_ref("main screen", monitors=mons)["id"] == 1
    assert mon_mod.resolve_monitor_ref("other screen", relative_to=1, monitors=mons)["id"] == 2
    assert mon_mod.resolve_monitor_ref("the other screen", relative_to=2, monitors=mons)["id"] == 1
    assert mon_mod.resolve_monitor_ref(2, monitors=mons)["id"] == 2
    print("OK NL resolve")


def test_extract_monitor_ref():
    from neuron.windows import monitors as mon_mod

    assert mon_mod.extract_monitor_ref("Open YouTube on screen 1.")
    assert "other" in (mon_mod.extract_monitor_ref("Move Blender to the other screen.") or "").lower()
    assert mon_mod.extract_monitor_ref("put this on the left monitor")
    assert mon_mod.extract_monitor_ref("open notepad") is None
    print("OK extract phrases")


def test_get_monitors_tool():
    from neuron.windows import monitors as mon_mod

    with mock.patch.object(mon_mod, "list_monitor_dicts", return_value=_fake_mons()):
        r = mon_mod.get_monitors({})
    assert r.success
    assert r.state["count"] == 2
    assert any(m["id"] == 1 for m in r.state["monitors"])
    print("OK get_monitors", r.message[:80])


def test_get_windows_by_monitor():
    from neuron.windows import monitors as mon_mod

    wins = [
        {"title": "YouTube - Chrome", "hwnd": 11, "left": 100, "top": 100, "width": 800, "height": 600, "monitor_id": 1},
        {"title": "Blender", "hwnd": 22, "left": 2000, "top": 100, "width": 900, "height": 700, "monitor_id": 2},
        {"title": "Discord", "hwnd": 33, "left": 50, "top": 50, "width": 400, "height": 400, "monitor_id": 1},
    ]
    with mock.patch.object(mon_mod, "list_monitor_dicts", return_value=_fake_mons()), mock.patch.object(
        mon_mod, "_list_windows_with_monitor", return_value=wins
    ):
        r = mon_mod.get_windows_by_monitor({"monitor": "screen 1"})
        assert r.success
        assert r.state["count"] == 2
        r2 = mon_mod.get_windows_by_monitor({"monitor": "right"})
        assert r2.success
        assert r2.state["count"] == 1
        assert "Blender" in (r2.state["windows"][0]["title"])
    print("OK windows by monitor")


def test_move_window_to_other_screen_verify():
    from neuron.windows import monitors as mon_mod
    from neuron.windows.result import ok as ok_res

    mons = _fake_mons()
    blender = {
        "title": "Blender",
        "hwnd": 99,
        "left": 100,
        "top": 100,
        "width": 800,
        "height": 600,
        "monitor_id": 1,
    }
    after = {
        "title": "Blender",
        "hwnd": 99,
        "left": 1960,
        "top": 40,
        "width": 800,
        "height": 600,
        "monitor_id": 2,
    }

    with mock.patch.object(mon_mod, "list_monitor_dicts", return_value=mons), mock.patch.object(
        mon_mod, "_resolve_window", return_value=(99, blender)
    ), mock.patch.object(mon_mod, "_window_by_hwnd", return_value=after), mock.patch(
        "ctypes.windll.user32.ShowWindow", return_value=True
    ), mock.patch(
        "ctypes.windll.user32.MoveWindow", return_value=True
    ), mock.patch(
        "neuron.windows.state.focus_hwnd", return_value=True
    ), mock.patch(
        "time.sleep", return_value=None
    ):
        r = mon_mod.move_window_to_monitor({"name": "Blender", "monitor": "other screen"})
    assert r.success
    assert r.state.get("verified") is True
    assert r.state.get("after_monitor") == 2
    assert r.state.get("before_monitor") == 1
    print("OK move to other screen", r.message)


def test_registry_phase10_tools():
    from neuron.brain import tool_registry
    import brain  # noqa: F401

    tool_registry.reset_for_tests()
    tool_registry.ensure_bootstrapped()
    names = set(tool_registry.names())
    for n in ("get_monitors", "get_windows_by_monitor", "capture_monitor", "move_window_to_monitor"):
        assert n in names, n
    doc = tool_registry.tools_doc(90)
    assert "get_windows_by_monitor" in doc
    print("OK registry phase10")


def test_live_get_monitors_smoke():
    from neuron.windows import monitors as mon_mod

    r = mon_mod.get_monitors({})
    assert r.success or r.error
    if r.success:
        assert r.state.get("monitors")
        assert r.state["monitors"][0]["width"] > 0
        print("OK live monitors", r.message[:120])
    else:
        print("SKIP live monitors", r.error)


if __name__ == "__main__":
    test_annotate_roles_geometry()
    test_resolve_nl_refs()
    test_extract_monitor_ref()
    test_get_monitors_tool()
    test_get_windows_by_monitor()
    test_move_window_to_other_screen_verify()
    test_registry_phase10_tools()
    test_live_get_monitors_smoke()
    print("\nPhase 10 multi-monitor tests passed.")
