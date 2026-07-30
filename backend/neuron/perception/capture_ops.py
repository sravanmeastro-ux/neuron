"""Phase 5 capture helpers — resize/crop aware, local only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from neuron.windows.result import ToolResult, fail, ok


def _out_dir() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "tts_out"
    d.mkdir(exist_ok=True)
    return d


def _vision_cfg() -> dict:
    try:
        import json
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        return cfg.get("vision") or {}
    except Exception:
        return {}


def prepare_image(img, *, max_width: int | None = None, quality: int | None = None):
    """Downscale for OCR/VLM to save CPU/GPU."""
    import screen_capture as sc
    vcfg = _vision_cfg()
    max_w = int(max_width if max_width is not None else vcfg.get("glance_max_width", 1024) or 1024)
    img = sc.downscale(img, max_w=max_w)
    return img


def get_cursor_position(args: dict | None = None) -> ToolResult:
    try:
        import ctypes
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        x, y = int(pt.x), int(pt.y)
        mon_id = 1
        try:
            import screen_capture as sc
            mon = sc.monitor_for_point(x, y)
            if mon:
                mon_id = int(getattr(mon, "id", 1) or 1)
        except Exception:
            pass
        return ok(
            f"Cursor at ({x}, {y}) on monitor {mon_id}.",
            state={"x": x, "y": y, "monitor": mon_id},
            method="win32",
        )
    except Exception:
        try:
            import pyautogui
            x, y = pyautogui.position()
            return ok(
                f"Cursor at ({x}, {y}).",
                state={"x": int(x), "y": int(y), "monitor": 1},
                method="pyautogui",
            )
        except Exception as exc:
            return fail(str(exc))


def capture_screen(args: dict | None = None) -> ToolResult:
    args = args or {}
    all_mons = bool(args.get("all") or args.get("all_monitors"))
    try:
        import screen_capture as sc
        if all_mons:
            img = sc.capture_virtual_desktop()
            path = _out_dir() / "screen_all.png"
        else:
            mons = sc.list_monitors()
            mon = mons[0] if mons else None
            if mon is None:
                return fail("No monitor.")
            img = sc.capture_monitor(mon)
            path = _out_dir() / "screen.png"
        img = prepare_image(img, max_width=int(args.get("max_width") or 1600))
        img.save(path)
        return ok(
            f"Captured screen: {path.name}",
            state={"path": str(path), "width": img.width, "height": img.height, "all": all_mons},
            method="win32",
        )
    except Exception as exc:
        # Legacy actions.screenshot fallback
        try:
            import actions
            msg = actions.screenshot(all_monitors=all_mons)
            return ok(str(msg), state={"fallback": True}, method="actions")
        except Exception as exc2:
            return fail(str(exc2 or exc))


def capture_monitor(args: dict | None = None) -> ToolResult:
    """Capture monitor by id or NL (left/right/main/screen 2)."""
    try:
        from neuron.windows import monitors as mon_mod
        return mon_mod.capture_monitor(args or {})
    except Exception as exc:
        # Fallback numeric-only path
        args = args or {}
        mid = int(args.get("monitor") or args.get("monitor_id") or 1)
        try:
            import screen_capture as sc
            mons = sc.list_monitors()
            mon = None
            for i, m in enumerate(mons or [], 1):
                if int(getattr(m, "id", i)) == mid or i == mid:
                    mon = m
                    break
            if mon is None and mons:
                mon = mons[0]
                mid = int(getattr(mon, "id", 1) or 1)
            if mon is None:
                return fail("No monitor.")
            img = sc.capture_monitor(mon)
            img = prepare_image(img, max_width=int(args.get("max_width") or 1600))
            path = _out_dir() / f"mon_{mid}.png"
            img.save(path)
            return ok(
                f"Captured monitor {mid}: {path.name}",
                state={
                    "path": str(path),
                    "monitor": mid,
                    "width": img.width,
                    "height": img.height,
                    "left": int(getattr(mon, "left", 0)),
                    "top": int(getattr(mon, "top", 0)),
                },
                method="win32",
            )
        except Exception as exc2:
            return fail(str(exc2 or exc))


def get_active_window_screenshot(args: dict | None = None) -> ToolResult:
    args = args or {}
    try:
        import screen_capture as sc
        fg = sc.capture_foreground(padding=int(args.get("padding") or 0))
        if not fg or not fg.get("image"):
            return fail("No foreground window to capture.")
        img = prepare_image(fg["image"], max_width=int(args.get("max_width") or 1280))
        path = _out_dir() / "active_window.png"
        img.save(path)
        return ok(
            f"Captured active window: {fg.get('title') or path.name}",
            state={
                "path": str(path),
                "title": fg.get("title") or "",
                "monitor": int(fg.get("monitor_id") or 1),
                "bounds": {
                    "left": int(fg.get("left") or 0),
                    "top": int(fg.get("top") or 0),
                    "width": int(fg.get("width") or 0),
                    "height": int(fg.get("height") or 0),
                },
                "width": img.width,
                "height": img.height,
            },
            method="win32",
        )
    except Exception as exc:
        return fail(str(exc))
