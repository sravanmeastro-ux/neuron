"""Sticky monitor focus for N.E.U.R.O.N.

After "look at monitor 1", follow-up commands prefer that display
until cleared or TTL expires.
"""

from __future__ import annotations

import time

_FOCUS = {"id": None, "until": 0.0, "label": ""}


def set_focus(monitor_id: int, ttl_seconds: float = 180.0) -> str:
    mid = int(monitor_id)
    _FOCUS["id"] = mid
    _FOCUS["until"] = time.time() + float(ttl_seconds)
    _FOCUS["label"] = f"Monitor {mid}"
    return f"Focusing on monitor {mid}. I'll watch that screen and do what you say there."


def clear_focus() -> str:
    _FOCUS["id"] = None
    _FOCUS["until"] = 0.0
    _FOCUS["label"] = ""
    return "Okay — watching all screens again."


def get_focus() -> int | None:
    if _FOCUS["id"] is None:
        return None
    if time.time() > _FOCUS["until"]:
        clear_focus()
        return None
    # Sliding TTL while in use
    _FOCUS["until"] = time.time() + 180.0
    return int(_FOCUS["id"])


def status_line() -> str:
    mid = get_focus()
    if not mid:
        return ""
    return f"ACTIVE MONITOR FOCUS: Monitor {mid} — prefer this screen for clicks and vision."
