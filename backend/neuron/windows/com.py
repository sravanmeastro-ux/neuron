"""Ensure COM / UI Automation is initialized on the current thread."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def com_uia() -> Iterator[None]:
    """Initialize UIAutomation/COM for this thread (safe no-op if already set)."""
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread(debug=False):
            yield
        return
    except Exception:
        pass
    try:
        import ctypes
        hr = ctypes.windll.ole32.CoInitialize(None)
        try:
            yield
        finally:
            # S_FALSE (1) means already initialized — don't uninit shared apartment
            if hr in (0,):  # S_OK only
                ctypes.windll.ole32.CoUninitialize()
    except Exception:
        yield
