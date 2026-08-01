"""Early intent execution from partial transcripts.

Calls FastIntentRouter without modifying it — only short Category-A-safe
commands that already look complete.
"""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.streaming_voice.config import early_intent_enabled

# Tight allowlist — never fire complex / multi-step from partials
_EARLY_RE = re.compile(
    r"^(?:please\s+)?(?:"
    r"mute|unmute|"
    r"volume\s+(?:up|down)|"
    r"pause|play|"
    r"scroll(?:\s+(?:up|down))?|"
    r"page\s+(?:up|down)|"
    r"skip(?:\s+(?:the|this|that))?\s+(?:ad|ads)|"
    r"copy|paste|undo|"
    r"stop(?:\s+talking)?"
    r")[.!]?\s*$",
    re.I,
)

_last_fired: str = ""
_last_at: float = 0.0


def looks_early_executable(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if not _EARLY_RE.match(t):
        return False
    try:
        from neuron.speech.endpoint import is_short_safe_command, is_complete_command
        if is_short_safe_command(t):
            return True
        gate = is_complete_command(t)
        return bool(gate.accept and _EARLY_RE.match(gate.text))
    except Exception:
        return True


def try_early_intent(text: str, *, busy: bool = False) -> dict[str, Any] | None:
    """
    Attempt FastIntentRouter on a partial/final-looking short command.
    Returns meta dict if acted, else None.
    """
    global _last_fired, _last_at
    if not early_intent_enabled() or busy:
        return None
    t = (text or "").strip()
    if not looks_early_executable(t):
        return None
    # Dedupe within 2.5s
    now = time.time()
    if t.lower() == _last_fired.lower() and (now - _last_at) < 2.5:
        return None

    t0 = time.perf_counter()
    try:
        from neuron.brain import fast_router
        fr = fast_router.try_handle(t)
        if fr is None or not fr.ok or not fr.acted or fr.used_agent_loop:
            return None
        if fr.meta.get("fallback_agent"):
            return None
        ms = round((time.perf_counter() - t0) * 1000, 2)
        _last_fired = t
        _last_at = now
        return {
            "ok": True,
            "say": fr.say or "",
            "text": t,
            "early_intent_ms": ms,
            "path": "early_intent",
            "used_agent_loop": False,
            "fast": fr.meta,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "text": t}


def was_early_fired(text: str, *, window_s: float = 3.0) -> bool:
    if not text or not _last_fired:
        return False
    if time.time() - _last_at > window_s:
        return False
    a = re.sub(r"\W+", "", text.lower())
    b = re.sub(r"\W+", "", _last_fired.lower())
    return a == b or a.startswith(b) or b.startswith(a)
