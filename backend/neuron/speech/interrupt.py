"""V2 voice interruption — stop TTS and abort in-flight AgentLoop work.

Examples that request an interrupt:
  "Neuron, stop."
  "stop talking"
  "be quiet" / "shut up" / "silence"
  "halt" / "cancel that" / "abort"

Call request() as soon as the phrase (or barge-in) is heard.
AgentLoop / executor poll interrupted() between steps and bail out.
"""

from __future__ import annotations

import re
import threading
from typing import Callable

# Explicit stop / barge-in phrases (not "stop the video", "stop recording").
STOP_RE = re.compile(
    r"(?:"
    r"\b(?:hey\s+)?(?:neuron|jarvis)[,.]?\s+(?:stop|cancel)\b"
    r"|\b(?:stop|cancel)[,.]?\s+(?:neuron|jarvis)\b"
    r"|\bstop\s+talking\b"
    r"|\bstop\s+speaking\b"
    r"|\bbe\s+quiet\b"
    r"|\bshut\s+up\b"
    r"|\bsilence\b"
    r"|\bhalt\b"
    r"|\babort\b"
    r"|\bcancel\s+that\b"
    r"|\bcancel\s+(?:it|this|the\s+task|the\s+operation)\b"
    r"|\bnever\s*mind\b"
    r"|\bcut\s+it\s+out\b"
    r"|(?:^|\b)(?:please\s+)?(?:stop|cancel)(?:\s+please)?[.!]?$"
    r")",
    re.I,
)

_lock = threading.Lock()
_flag = False
_generation = 0  # bumps on each request so mid-flight work can detect freshness
_listeners: list[Callable[[], None]] = []


def is_stop_phrase(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(STOP_RE.search(t))


def request(*, reason: str = "") -> int:
    """Raise interrupt — stop speech + cancel current task ASAP."""
    global _flag, _generation
    with _lock:
        _flag = True
        _generation += 1
        gen = _generation
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn()
        except Exception:
            pass
    try:
        from neuron.speech.session import get_session
        get_session().request_interrupt()
    except Exception:
        pass
    try:
        from neuron.speech.tts import stop_speaking
        stop_speaking()
    except Exception:
        pass
    if reason:
        print(f"[interrupt] requested ({reason}) gen={gen}", flush=True)
    else:
        print(f"[interrupt] requested gen={gen}", flush=True)
    return gen


def clear() -> bool:
    """Clear interrupt flag (start of a new command). Returns prior state."""
    global _flag
    with _lock:
        was = _flag
        _flag = False
    try:
        from neuron.speech.session import get_session
        get_session().clear_interrupt()
    except Exception:
        pass
    return was


def interrupted() -> bool:
    with _lock:
        if _flag:
            return True
    try:
        from neuron.speech.session import get_session
        return bool(get_session().interrupt_requested)
    except Exception:
        return False


def generation() -> int:
    with _lock:
        return _generation


def on_interrupt(fn: Callable[[], None]) -> None:
    """Register a side-effect callback (e.g. cancel audio)."""
    with _lock:
        _listeners.append(fn)


def status() -> dict:
    with _lock:
        return {
            "interrupted": _flag,
            "generation": _generation,
        }
