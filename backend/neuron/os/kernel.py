"""NEURON OS kernel — boot once, hold session + capability map."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from neuron.os import capabilities as caps
from neuron.os.types import OsReport, OsResult

_LOCK = threading.RLock()
_BOOTED = False
_BOOT_MS = 0.0
_SESSION = ""
_DISPATCH = 0
_LAST_CAP = ""


def boot(*, force: bool = False) -> OsReport:
    global _BOOTED, _BOOT_MS, _SESSION, _DISPATCH, _LAST_CAP
    with _LOCK:
        if _BOOTED and not force:
            return status()
        t0 = time.perf_counter()
        registered = caps.bootstrap_capabilities()
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
        except Exception:
            pass
        _BOOT_MS = round((time.perf_counter() - t0) * 1000, 2)
        _SESSION = uuid.uuid4().hex[:10]
        _DISPATCH = 0
        _LAST_CAP = ""
        _BOOTED = True
        return OsReport(
            session_id=_SESSION,
            capabilities=registered,
            boot_ms=_BOOT_MS,
            dispatch_count=0,
        )


def status() -> OsReport:
    return OsReport(
        session_id=_SESSION or "(not booted)",
        capabilities=[c["id"] for c in caps.list_capabilities() if c.get("registered")],
        last_capability=_LAST_CAP,
        boot_ms=_BOOT_MS,
        dispatch_count=_DISPATCH,
    )


def dispatch(capability: str, args: dict[str, Any] | None = None) -> OsResult:
    global _DISPATCH, _LAST_CAP
    boot()
    handler = caps.get(capability)
    if not handler:
        return OsResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)
    result = handler(args or {})
    with _LOCK:
        _DISPATCH += 1
        _LAST_CAP = capability
    return result


def is_booted() -> bool:
    return _BOOTED
