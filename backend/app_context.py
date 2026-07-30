"""Remember which app NEURON is currently controlling.

After learn / steam_goto / open, follow-ups like "scroll down" apply to
that app instead of whatever window happens to have focus (often NEURON itself).
"""

from __future__ import annotations

import time

_STATE = {"app": "", "until": 0.0}


def set_app(name: str, ttl_seconds: float = 600.0) -> None:
    key = (name or "").strip().lower()
    if not key:
        return
    _STATE["app"] = key
    _STATE["until"] = time.time() + float(ttl_seconds)


def get_app() -> str:
    if not _STATE["app"]:
        return ""
    if time.time() > _STATE["until"]:
        _STATE["app"] = ""
        return ""
    # Keep alive while commands keep coming.
    _STATE["until"] = time.time() + 600.0
    return _STATE["app"]


def current_app() -> str:
    """Alias used by context gather / perception."""
    return get_app()


def clear() -> None:
    _STATE["app"] = ""
    _STATE["until"] = 0.0
