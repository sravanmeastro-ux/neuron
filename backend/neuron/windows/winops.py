"""Phase 2 window / monitor geometry tools (+ Phase 10 multi-monitor)."""

from __future__ import annotations

import time

from neuron.windows import monitors as mon_mod
from neuron.windows import state as win_state
from neuron.windows.resolve import resolve
from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[win-ops] {msg}", flush=True)


def get_monitors(args: dict | None = None) -> ToolResult:
    return mon_mod.get_monitors(args)


def get_windows_by_monitor(args: dict | None = None) -> ToolResult:
    return mon_mod.get_windows_by_monitor(args)


def move_window_to_monitor(args: dict | None = None) -> ToolResult:
    return mon_mod.move_window_to_monitor(args)


def get_windows(args: dict | None = None) -> ToolResult:
    wins = win_state.list_top_windows(int((args or {}).get("limit") or 40))
    mons = mon_mod.list_monitor_dicts()
    enriched = []
    for w in wins:
        row = dict(w)
        row["monitor_id"] = mon_mod.window_monitor_id(row, mons)
        enriched.append(row)
    titles = [w.get("title") for w in enriched]
    return ok(
        "Windows: " + ("; ".join(titles[:25]) if titles else "none"),
        state={"windows": enriched, "monitors": mons},
        method="uia",
    )


def get_active_window(args: dict | None = None) -> ToolResult:
    fg = win_state.get_foreground()
    if not fg:
        return fail("No active window.", method="uia")
    title = fg.get("title") or "(untitled)"
    mons = mon_mod.list_monitor_dicts()
    mid = mon_mod.foreground_monitor_id(mons)
    state: dict = {"active": fg, "monitor_id": mid}
    if mid:
        for m in mons:
            if int(m["id"]) == int(mid):
                state["monitor"] = m
                break
    return ok(
        f"Active: {title}" + (f" on monitor {mid}" if mid else ""),
        state=state,
        method="uia",
    )


def _resolve_hwnd(args: dict) -> int:
    title = (args.get("title") or args.get("name") or args.get("app") or "").strip()
    if title:
        resolved = resolve(title)
        wins = win_state.find_app_windows(resolved)
        if wins:
            return int(wins[0].get("hwnd") or 0)
        return win_state.find_window_hwnd(title)
    return int((win_state.get_foreground() or {}).get("hwnd") or 0)


def move_window(args: dict | None = None) -> ToolResult:
    """Move by monitor id/NL or absolute x,y. Prefer move_window_to_monitor for NL screens."""
    args = args or {}
    ref = args.get("monitor") or args.get("monitor_id") or args.get("screen") or args.get("display")
    if ref not in (None, "", 0, "0") and args.get("x") is None and args.get("y") is None:
        return mon_mod.move_window_to_monitor(args)

    before = win_state.snapshot("move_window")
    hwnd = _resolve_hwnd(args)
    if not hwnd:
        return fail("No window to move.", state={"before": before})

    x = args.get("x")
    y = args.get("y")
    left, top = 40, 40
    if x is not None:
        left = int(x)
    if y is not None:
        top = int(y)

    width, height = 900, 700
    for w in win_state.list_top_windows(50):
        if int(w.get("hwnd") or 0) == hwnd:
            width = max(200, int(w.get("width") or width))
            height = max(150, int(w.get("height") or height))
            break

    try:
        import ctypes
        ctypes.windll.user32.MoveWindow(hwnd, left, top, width, height, True)
        win_state.focus_hwnd(hwnd)
        time.sleep(0.15)
        after = win_state.snapshot("move_window")
        return ok(
            f"Moved window to ({left},{top}).",
            state={"before": before, "after": after, "hwnd": hwnd, "x": left, "y": top},
            method="win32",
        )
    except Exception as exc:
        return fail(f"move_window failed: {exc}", state={"before": before, "hwnd": hwnd})


def resize_window(args: dict | None = None) -> ToolResult:
    args = args or {}
    before = win_state.snapshot("resize_window")
    hwnd = _resolve_hwnd(args)
    if not hwnd:
        return fail("No window to resize.", state={"before": before})

    width = int(args.get("width") or args.get("w") or 0)
    height = int(args.get("height") or args.get("h") or 0)
    if width < 200 or height < 150:
        return fail("Need width (>=200) and height (>=150).")

    left, top = 40, 40
    for w in win_state.list_top_windows(50):
        if int(w.get("hwnd") or 0) == hwnd:
            left = int(w.get("left") or left)
            top = int(w.get("top") or top)
            break

    try:
        import ctypes
        ctypes.windll.user32.MoveWindow(hwnd, left, top, width, height, True)
        time.sleep(0.15)
        after = win_state.snapshot("resize_window")
        verified = False
        for w in after.get("windows") or []:
            if int(w.get("hwnd") or 0) == hwnd:
                verified = abs(int(w.get("width") or 0) - width) < 80
                break
        return ok(
            f"Resized window to {width}x{height}.",
            state={
                "before": before,
                "after": after,
                "hwnd": hwnd,
                "width": width,
                "height": height,
                "verified": verified,
            },
            method="win32",
        )
    except Exception as exc:
        return fail(f"resize_window failed: {exc}", state={"before": before, "hwnd": hwnd})
