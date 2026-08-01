"""Multi-channel workflow recorder — mouse, keyboard, apps, clipboard, browser, timing, focus."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from neuron.workflows import store
from neuron.workflows.types import Workflow, WorkflowStep

_LOCK = threading.Lock()
_thread: threading.Thread | None = None
_recording = False
_session: dict[str, Any] = {}
_CHANNELS_DEFAULT = [
    "mouse",
    "keyboard",
    "applications",
    "clipboard",
    "browser",
    "timing",
    "window_focus",
]


def _cfg() -> dict:
    try:
        root = Path(__file__).resolve().parents[2]
        return json.loads((root / "config.json").read_text(encoding="utf-8")).get("workflows") or {}
    except Exception:
        return {}


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _max_steps() -> int:
    return max(5, int(_cfg().get("max_steps", 80) or 80))


def _poll() -> float:
    return max(0.03, float(_cfg().get("poll_seconds", 0.05) or 0.05))


def _idle_wait_ms() -> float:
    """Insert wait step when gap between events exceeds this (ms)."""
    return max(200.0, float(_cfg().get("idle_wait_ms", 800) or 800))


def is_recording() -> bool:
    return _recording


def status() -> dict[str, Any]:
    with _LOCK:
        return {
            "recording": _recording,
            "steps": len(_session.get("steps") or []),
            "name": _session.get("name") or "",
            "channels": list(_session.get("channels") or []),
            "app": _session.get("last_app") or "",
        }


def _cursor_pos() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _key_down(vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _foreground() -> tuple[str, str]:
    try:
        import uiautomation as auto
        fg = auto.GetForegroundControl()
        if not fg:
            return "", ""
        title = (fg.Name or "").strip()[:160]
        try:
            import psutil
            stem = Path(psutil.Process(fg.ProcessId).name()).stem.lower()
        except Exception:
            stem = ""
        return stem, title
    except Exception:
        return "", ""


def _element_at(x: int, y: int) -> dict:
    info: dict[str, Any] = {"name": "", "control_type": "", "automation_id": ""}
    try:
        import uiautomation as auto
        ctrl = auto.ControlFromPoint(x, y)
        if not ctrl:
            return info
        info["name"] = (ctrl.Name or "").strip()[:120]
        try:
            info["control_type"] = str(ctrl.ControlTypeName or "")
        except Exception:
            pass
        try:
            info["automation_id"] = (ctrl.AutomationId or "").strip()[:120]
        except Exception:
            pass
    except Exception:
        pass
    return info


def _clipboard_text() -> str:
    try:
        import ctypes
        from ctypes import wintypes

        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(0):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                text = ctypes.wstring_at(ptr)
                return (text or "")[:2000]
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


def _browser_url(app: str, title: str) -> str:
    """Best-effort URL from Chrome/Edge address bar or title."""
    browsers = ("chrome", "msedge", "brave", "firefox", "opera")
    if app not in browsers:
        return ""
    # Title often "Page - Google Chrome"
    if "http://" in title or "https://" in title:
        for part in title.split():
            if part.startswith("http"):
                return part.strip()[:500]
    try:
        import uiautomation as auto
        fg = auto.GetForegroundControl()
        if not fg:
            return ""
        # Common address bar AutomationId / Name
        for aid in ("address", "omnibox", "url", "Address and search bar"):
            try:
                edit = fg.EditControl(searchDepth=8, Name=aid) if len(aid) > 3 else None
            except Exception:
                edit = None
            if edit is None:
                try:
                    edit = fg.EditControl(searchDepth=8, AutomationId="address")
                except Exception:
                    edit = None
            if edit:
                try:
                    val = edit.GetValuePattern().Value
                    if val and ("." in val or val.startswith("http")):
                        return str(val)[:500]
                except Exception:
                    pass
        # Fallback: first EditControl with http/dot
        try:
            for ed in fg.GetChildren():
                pass
        except Exception:
            pass
    except Exception:
        pass
    return ""


def _ignore(app: str, title: str) -> bool:
    blob = f"{app} {title}".lower()
    return any(s in blob for s in ("neuron", "n.e.u.r.o.n", "program manager"))


def _append(step: WorkflowStep) -> None:
    with _LOCK:
        steps: list = _session.setdefault("steps", [])
        if len(steps) >= _max_steps():
            return
        now = time.time()
        last_t = float(_session.get("last_t") or 0)
        if last_t and "timing" in (_session.get("channels") or []):
            gap_ms = (now - last_t) * 1000.0
            if gap_ms >= _idle_wait_ms() and steps:
                steps.append(
                    WorkflowStep(
                        kind="wait",
                        args={"ms": int(min(gap_ms, 15000))},
                        t=now,
                    )
                )
        step.t = now
        steps.append(step)
        _session["last_t"] = now


# VK map for a useful keyboard subset
_VK_MAP = {
    0x08: "backspace",
    0x09: "tab",
    0x0D: "enter",
    0x1B: "esc",
    0x20: "space",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2E: "delete",
    0x70: "f1",
    0x71: "f2",
    0x72: "f3",
    0x73: "f4",
    0x74: "f5",
}
# Letters A-Z, digits 0-9
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _VK_MAP[0x41 + i] = ch.lower()
for i in range(10):
    _VK_MAP[0x30 + i] = str(i)

_VK_CTRL, _VK_SHIFT, _VK_ALT = 0x11, 0x10, 0x12
_VK_LBUTTON, _VK_RBUTTON = 0x01, 0x02


def _loop() -> None:
    global _recording
    left_was = right_was = False
    key_was: dict[int, bool] = {vk: False for vk in _VK_MAP}
    last_app, last_title = "", ""
    last_clip = _clipboard_text()
    type_buf: list[str] = []
    type_last = 0.0

    def flush_type() -> None:
        nonlocal type_buf, type_last
        if not type_buf:
            return
        if "keyboard" not in (_session.get("channels") or []):
            type_buf = []
            return
        text = "".join(type_buf)
        type_buf = []
        if text.strip():
            _append(WorkflowStep(kind="type", args={"text": text}))

    while _recording:
        try:
            channels = set(_session.get("channels") or _CHANNELS_DEFAULT)
            app, title = _foreground()

            # Window focus / applications
            if (app, title) != (last_app, last_title) and app:
                if not _ignore(app, title):
                    if "window_focus" in channels or "applications" in channels:
                        flush_type()
                        _append(
                            WorkflowStep(
                                kind="focus",
                                args={"app": app, "title": title},
                            )
                        )
                    if "applications" in channels and app != last_app and last_app:
                        _append(WorkflowStep(kind="app", args={"name": app}))
                    if "browser" in channels:
                        url = _browser_url(app, title)
                        if url:
                            _append(WorkflowStep(kind="browser", args={"url": url, "app": app}))
                last_app, last_title = app, title
                _session["last_app"] = app

            # Mouse
            if "mouse" in channels:
                left = _key_down(_VK_LBUTTON)
                right = _key_down(_VK_RBUTTON)
                if left and not left_was:
                    flush_type()
                    x, y = _cursor_pos()
                    if not _ignore(app, title):
                        el = _element_at(x, y)
                        _append(
                            WorkflowStep(
                                kind="mouse",
                                args={
                                    "button": "left",
                                    "x": x,
                                    "y": y,
                                    "app": app,
                                    "title": title,
                                    "element": el,
                                },
                            )
                        )
                if right and not right_was:
                    flush_type()
                    x, y = _cursor_pos()
                    if not _ignore(app, title):
                        el = _element_at(x, y)
                        _append(
                            WorkflowStep(
                                kind="mouse",
                                args={
                                    "button": "right",
                                    "x": x,
                                    "y": y,
                                    "app": app,
                                    "title": title,
                                    "element": el,
                                },
                            )
                        )
                left_was, right_was = left, right

            # Keyboard
            if "keyboard" in channels:
                ctrl = _key_down(_VK_CTRL)
                shift = _key_down(_VK_SHIFT)
                alt = _key_down(_VK_ALT)
                for vk, name in _VK_MAP.items():
                    down = _key_down(vk)
                    if down and not key_was[vk]:
                        if ctrl or alt:
                            flush_type()
                            parts = []
                            if ctrl:
                                parts.append("ctrl")
                            if alt:
                                parts.append("alt")
                            if shift:
                                parts.append("shift")
                            parts.append(name)
                            _append(WorkflowStep(kind="hotkey", args={"keys": "+".join(parts)}))
                        elif name in ("enter", "tab", "esc", "backspace", "delete", "left", "right", "up", "down") or name.startswith("f"):
                            flush_type()
                            _append(WorkflowStep(kind="key", args={"key": name}))
                        else:
                            ch = name.upper() if shift and len(name) == 1 and name.isalpha() else name
                            if ch == "space":
                                ch = " "
                            type_buf.append(ch if len(ch) == 1 else "")
                            type_last = time.time()
                    key_was[vk] = down
                if type_buf and (time.time() - type_last) > 0.45:
                    flush_type()

            # Clipboard
            if "clipboard" in channels:
                clip = _clipboard_text()
                if clip and clip != last_clip:
                    flush_type()
                    _append(
                        WorkflowStep(
                            kind="clipboard",
                            args={"op": "set", "text": clip[:500]},
                        )
                    )
                    last_clip = clip
        except Exception as exc:
            print(f"[workflows.recorder] {exc}", flush=True)
        time.sleep(_poll())

    flush_type()


def start(name: str = "", channels: list[str] | None = None) -> dict[str, Any]:
    global _recording, _thread, _session
    if not enabled():
        return {"ok": False, "error": "Workflow recording disabled in config."}
    if _recording:
        return {"ok": False, "error": "Already recording.", **status()}
    ch = list(channels or _cfg().get("channels") or _CHANNELS_DEFAULT)
    _session = {
        "name": (name or "").strip() or "untitled workflow",
        "channels": ch,
        "steps": [],
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_t": time.time(),
        "last_app": "",
        "variables": {},
    }
    _recording = True
    _thread = threading.Thread(target=_loop, name="workflow-recorder", daemon=True)
    _thread.start()
    return {"ok": True, "message": "Recording workflow.", **status()}


def stop(name: str = "", *, save: bool = True) -> dict[str, Any]:
    global _recording
    if not _recording and not (_session.get("steps")):
        return {"ok": False, "error": "Not recording."}
    _recording = False
    time.sleep(_poll() * 2)
    with _LOCK:
        steps = list(_session.get("steps") or [])
        label = (name or _session.get("name") or "workflow").strip()
        channels = list(_session.get("channels") or [])
        variables = dict(_session.get("variables") or {})
    if not steps:
        return {"ok": False, "error": "No steps captured.", "steps": 0}
    if not save:
        return {"ok": True, "saved": False, "steps": [s.to_dict() for s in steps]}
    wf = Workflow(
        id=store.new_id(label),
        name=label,
        description=f"Recorded workflow ({len(steps)} steps)",
        variables=variables,
        steps=steps,
        channels=channels,
        tags=["recorded"],
    )
    store.save(wf)
    return {"ok": True, "saved": True, "workflow": wf.summary(), "id": wf.id}


def cancel() -> dict[str, Any]:
    global _recording, _session
    was = _recording
    _recording = False
    _session = {"steps": []}
    return {"ok": True, "cancelled": was}
