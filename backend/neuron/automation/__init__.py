"""Low-level automation helpers (pywinauto optional)."""

from __future__ import annotations


def connect_app(title_re: str = ".*"):
    """Connect to an open app via pywinauto UIA backend."""
    try:
        from pywinauto import Application
        return Application(backend="uia").connect(title_re=title_re, timeout=3)
    except Exception as exc:
        raise RuntimeError(f"pywinauto connect failed: {exc}") from exc


def focus_by_title(title_re: str) -> bool:
    """Best-effort focus via pywinauto; returns True on success."""
    try:
        app = connect_app(title_re)
        app.top_window().set_focus()
        return True
    except Exception:
        return False
