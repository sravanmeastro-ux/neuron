"""App learning helpers for N.E.U.R.O.N.

By default NEURON does NOT scan every focused window (that spam is off).
OS-wide knowledge comes from pc_trainer inventory ("learn my computer").
Deep UI learn runs only when:
  - you say "learn how <app> works", or
  - learn_on_open is enabled and NEURON opens an app, or
  - watch_foreground is explicitly enabled in config.
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


def watch_foreground_enabled() -> bool:
    """Foreground watcher — off by default (was causing learn-spam on every app)."""
    return bool(_cfg().get("watch_foreground", False)) and is_enabled()


def learn_on_open_enabled() -> bool:
    return bool(_cfg().get("learn_on_open", False)) and is_enabled()


def _quiet() -> bool:
    return bool(_cfg().get("quiet", True))


def _log(msg: str) -> None:
    if _quiet() and ("Already know" in msg or "skip" in msg.lower()):
        return
    print(f"[auto_learn] {msg}", flush=True)


def _ignore_title(title: str) -> bool:
    t = (title or "").lower()
    if not t or len(t) < 2:
        return True
    skip = (
        "n.e.u.r.o.n", "neuron", "program manager", "task switching",
        "task view", "windows input experience", "nvidia geforce overlay",
        "cursor",
    )
    return any(s in t for s in skip)


def schedule_learn(app_hint: str = "", *, settle_s: float = None, force: bool = False):
    """Queue a background deep-learn for one app.

    Skipped unless force=True, or learn_on_open / watch_foreground is on.
    """
    if not force and not is_enabled():
        return
    # Explicit "learn how X works" uses app_learner directly (force).
    # schedule_learn from open_app / watcher needs the matching flag.
    if not force and not learn_on_open_enabled() and not watch_foreground_enabled():
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
                _log(msg)
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

    _last_fg = title
    hint = _app_hint_from_window(title, proc)
    schedule_learn(hint, settle_s=_cfg().get("fg_settle_seconds", 1.5))


def start_watcher():
    """Optional: poll focused windows and deep-learn them (OFF by default)."""
    global _watcher_started
    if _watcher_started:
        return
    if not watch_foreground_enabled():
        print(
            "[auto_learn] foreground watcher OFF "
            "(use 'learn my computer' for OS map, 'learn how X works' for one app)",
            flush=True,
        )
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
