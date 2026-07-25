"""Auto app-understanding for N.E.U.R.O.N.

When an app is opened (by NEURON or by the user), a foreground watcher
notices the active window, scans its UI (accessibility tree + optional
vision), and saves how-to knowledge under app_memory/ — so later voice
commands already know how that app works.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_lock = threading.Lock()
_pending = set()
_last_fg = ""
_watcher_started = False


def _cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("auto_learn", {}) or {}
    except Exception:
        return {}


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _ignore_title(title: str) -> bool:
    t = (title or "").lower()
    if not t or len(t) < 2:
        return True
    skip = (
        "n.e.u.r.o.n", "neuron", "program manager", "task switching",
        "task view", "windows input experience", "nvidia geforce overlay",
        "cursor",  # don't auto-learn the IDE while editing; explicit open_app still can
    )
    # Allow learning Cursor if explicitly opened via open_app — handled by force flag
    return any(s in t for s in skip)


def schedule_learn(app_hint: str = "", *, settle_s: float = None, force: bool = False):
    """Queue a background learn for the app that is/will be in the foreground.

    Non-blocking. Debounced per app slug so opening Steam library then
    community does not re-learn twice in a row.
    """
    if not is_enabled() and not force:
        return
    hint = (app_hint or "").strip() or "foreground"
    cfg = _cfg()
    settle = float(settle_s if settle_s is not None else cfg.get("settle_seconds", 2.5))

    with _lock:
        key = hint.lower()
        if key in _pending:
            return
        _pending.add(key)

    def worker():
        try:
            time.sleep(settle)
            import uiautomation as auto
            with auto.UIAutomationInitializerInThread(debug=False):
                import app_learner
                msg = app_learner.learn_app(
                    hint if hint != "foreground" else "this",
                    auto=True,
                    open_if_needed=False,
                    force=force,
                )
            if msg:
                print(f"[auto_learn] {msg}", flush=True)
        except Exception as exc:
            print(f"[auto_learn] failed: {exc}", flush=True)
        finally:
            with _lock:
                _pending.discard(key)

    threading.Thread(target=worker, daemon=True, name=f"auto-learn-{hint[:20]}").start()


def _app_hint_from_window(title: str, process: str = "") -> str:
    """Turn 'Untitled - Notepad' / chrome.exe into a stable learn hint."""
    t = (title or "").strip()
    p = (process or "").strip().lower().replace(".exe", "")
    known = {
        "steam": "steam",
        "notepad": "notepad",
        "chrome": "chrome",
        "msedge": "edge",
        "firefox": "firefox",
        "explorer": "file explorer",
        "code": "vscode",
        "devenv": "visual studio",
        "spotify": "spotify",
        "discord": "discord",
        "slack": "slack",
        "outlook": "outlook",
        "winword": "word",
        "excel": "excel",
        "powerpnt": "powerpoint",
    }
    if p in known:
        return known[p]
    for key, hint in known.items():
        if key in p or key in t.lower():
            return hint
    # "Document - AppName" → prefer right side when it looks like an app name
    for sep in (" — ", " - ", " | "):
        if sep in t:
            left, right = t.rsplit(sep, 1)
            right = right.strip()
            left = left.strip()
            if right and len(right) < 40 and not right.lower().startswith("http"):
                return right
            return left or t
    return t.split(" - ")[0].strip() or t


def _foreground_meta() -> tuple[str, str]:
    """Return (window title, process name) for the active window."""
    try:
        import uiautomation as auto
        root = auto.GetForegroundControl()
        if not root:
            return "", ""
        title = (root.Name or "").strip()
        proc = ""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = int(root.NativeWindowHandle)
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
            )
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(512)
                    size = wintypes.DWORD(512)
                    if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        proc = buf.value.split("\\")[-1]
                finally:
                    ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            try:
                proc = (root.ClassName or "").strip()
            except Exception:
                proc = ""
        return title, proc
    except Exception:
        return "", ""


def _poll_foreground_once():
    global _last_fg
    title, proc = _foreground_meta()
    if not title:
        return

    if title == _last_fg:
        return
    if _ignore_title(title):
        _last_fg = title
        return

    # New foreground app — learn it (unless we already know it well).
    _last_fg = title
    hint = _app_hint_from_window(title, proc)
    schedule_learn(hint, settle_s=_cfg().get("fg_settle_seconds", 1.5))


def start_watcher():
    """Poll the active window and auto-learn newly focused apps."""
    global _watcher_started
    if _watcher_started or not is_enabled():
        return
    _watcher_started = True
    interval = float(_cfg().get("poll_seconds", 2.0))

    def loop():
        import uiautomation as auto
        print("[auto_learn] foreground watcher started", flush=True)
        with auto.UIAutomationInitializerInThread(debug=False):
            while True:
                try:
                    _poll_foreground_once()
                except Exception as exc:
                    print(f"[auto_learn] watcher error: {exc}", flush=True)
                time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="app-watch").start()
