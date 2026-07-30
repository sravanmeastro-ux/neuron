"""Live Windows state: processes, windows, foreground, monitors."""

from __future__ import annotations

import time
from typing import Any

from neuron.windows.resolve import ResolvedApp, matches_process, matches_window_title


def _log(msg: str) -> None:
    print(f"[win-state] {msg}", flush=True)


def get_foreground() -> dict[str, Any]:
    try:
        from neuron.windows.com import com_uia
        import uiautomation as auto
        with com_uia():
            fg = auto.GetForegroundControl()
            if not fg:
                return {}
            rect = fg.BoundingRectangle
            return {
                "title": (fg.Name or "").strip(),
                "class": getattr(fg, "ClassName", "") or "",
                "hwnd": int(getattr(fg, "NativeWindowHandle", 0) or 0),
                "left": int(getattr(rect, "left", 0) or 0),
                "top": int(getattr(rect, "top", 0) or 0),
                "right": int(getattr(rect, "right", 0) or 0),
                "bottom": int(getattr(rect, "bottom", 0) or 0),
            }
    except Exception as exc:
        _log(f"foreground failed: {exc}")
        return {}


def list_top_windows(limit: int = 40) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from neuron.windows.com import com_uia
        import uiautomation as auto
        with com_uia():
            for w in auto.GetRootControl().GetChildren():
                try:
                    ctype = getattr(w, "ControlTypeName", "") or ""
                    if "Window" not in ctype and ctype not in ("WindowControl", "PaneControl"):
                        continue
                    title = (w.Name or "").strip()
                    if not title or len(title) < 2:
                        continue
                    if "n.e.u.r.o.n" in title.lower():
                        continue
                    rect = w.BoundingRectangle
                    rows.append({
                        "title": title[:120],
                        "hwnd": int(getattr(w, "NativeWindowHandle", 0) or 0),
                        "left": int(getattr(rect, "left", 0) or 0),
                        "top": int(getattr(rect, "top", 0) or 0),
                        "width": max(0, int(getattr(rect, "right", 0) - getattr(rect, "left", 0))),
                        "height": max(0, int(getattr(rect, "bottom", 0) - getattr(rect, "top", 0))),
                    })
                    if len(rows) >= limit:
                        break
                except Exception:
                    continue
        if rows:
            return rows
    except Exception as exc:
        _log(f"list_top_windows UIA failed: {exc}")
        # pywinauto fallback
        try:
            from pywinauto import Desktop
            for w in Desktop(backend="uia").windows():
                try:
                    title = (w.window_text() or "").strip()
                    if not title:
                        continue
                    rows.append({"title": title[:120], "hwnd": int(w.handle), "left": 0, "top": 0, "width": 0, "height": 0})
                    if len(rows) >= limit:
                        break
                except Exception:
                    continue
        except Exception as exc2:
            _log(f"list_top_windows pywinauto failed: {exc2}")
    return rows


def list_running_processes(limit: int = 80) -> list[str]:
    try:
        import psutil
        names = sorted({
            (p.info.get("name") or "").lower()
            for p in psutil.process_iter(["name"])
            if p.info.get("name")
        })
        return [n for n in names if n.endswith(".exe")][:limit]
    except Exception as exc:
        _log(f"processes failed: {exc}")
        return []


def list_monitors() -> list[dict[str, Any]]:
    try:
        from neuron.windows import monitors as mon_mod
        mons = mon_mod.list_monitor_dicts()
        if mons:
            return mons
    except Exception:
        pass
    try:
        import screen_capture
        mons = screen_capture.list_monitors() or []
        out = []
        for i, m in enumerate(mons, 1):
            if hasattr(m, "to_dict"):
                out.append(m.to_dict())
            elif isinstance(m, dict):
                out.append({
                    "id": int(m.get("id") or m.get("index") or i),
                    "left": int(m.get("left") or 0),
                    "top": int(m.get("top") or 0),
                    "width": int(m.get("width") or 0),
                    "height": int(m.get("height") or 0),
                    "primary": bool(m.get("primary")),
                })
            else:
                out.append({
                    "id": int(getattr(m, "id", i)),
                    "left": int(getattr(m, "left", 0)),
                    "top": int(getattr(m, "top", 0)),
                    "width": int(getattr(m, "width", 0)),
                    "height": int(getattr(m, "height", 0)),
                    "primary": bool(getattr(m, "primary", i == 1)),
                })
        if out:
            return out
    except Exception:
        pass
    try:
        import pyautogui
        w, h = pyautogui.size()
        return [{"id": 1, "left": 0, "top": 0, "width": w, "height": h, "primary": True}]
    except Exception:
        return []


def snapshot(request: str = "") -> dict[str, Any]:
    fg = get_foreground()
    return {
        "foreground": fg,
        "windows": list_top_windows(30),
        "processes_sample": list_running_processes(40),
        "monitors": list_monitors(),
        "request": (request or "")[:80],
        "ts": time.time(),
    }


def find_app_windows(resolved: ResolvedApp) -> list[dict[str, Any]]:
    return [w for w in list_top_windows(50) if matches_window_title(resolved, w.get("title") or "")]


def app_is_running(resolved: ResolvedApp) -> bool:
    if find_app_windows(resolved):
        return True
    for p in list_running_processes(120):
        if matches_process(resolved, p):
            return True
    return False


def find_window_hwnd(title_or_app: str = "", resolved: ResolvedApp | None = None) -> int:
    """Return HWND for matching window, else 0."""
    if resolved is not None:
        wins = find_app_windows(resolved)
        if wins:
            return int(wins[0].get("hwnd") or 0)
    needle = (title_or_app or "").strip().lower()
    if not needle:
        fg = get_foreground()
        return int(fg.get("hwnd") or 0)
    for w in list_top_windows(50):
        if needle in (w.get("title") or "").lower():
            return int(w.get("hwnd") or 0)
    return 0


def focus_hwnd(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception as exc:
        _log(f"focus_hwnd win32 failed: {exc}")
    # UIA fallback
    try:
        import uiautomation as auto
        for w in auto.GetRootControl().GetChildren():
            try:
                if int(getattr(w, "NativeWindowHandle", 0) or 0) == hwnd:
                    w.SetActive()
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def wait_for_app_window(resolved: ResolvedApp, timeout: float = 12.0) -> dict[str, Any] | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = find_app_windows(resolved)
        if wins:
            return wins[0]
        time.sleep(0.35)
    return None
