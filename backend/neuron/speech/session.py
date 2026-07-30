"""Conversation / hands-free session state for Phase 6 voice."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class VoiceSession:
    """Tracks wake / conversation arming and barge-in."""

    conversation_mode: bool = False
    armed_until: float = 0.0
    last_partial: str = ""
    last_final: str = ""
    listening: bool = True
    speaking: bool = False
    interrupt_requested: bool = False
    wake_events: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _cfg_timeout(self) -> float:
        try:
            import json
            from pathlib import Path
            voice = json.loads(
                (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
            ).get("voice") or {}
            return float(voice.get("conversation_timeout_seconds", 45) or 45)
        except Exception:
            return 45.0

    def arm(self, seconds: float | None = None) -> None:
        with self._lock:
            self.armed_until = time.time() + float(seconds if seconds is not None else self._cfg_timeout())

    def disarm(self) -> None:
        with self._lock:
            self.armed_until = 0.0

    def is_armed(self) -> bool:
        with self._lock:
            if self.conversation_mode:
                return True
            return time.time() < self.armed_until

    def set_conversation_mode(self, on: bool) -> str:
        with self._lock:
            self.conversation_mode = bool(on)
            if on:
                self.armed_until = time.time() + self._cfg_timeout()
                return (
                    "Conversation mode on — I won't need a wake word until you "
                    "say 'end conversation' or go quiet for a while."
                )
            self.armed_until = 0.0
            return "Conversation mode off. Say Neuron if wake word is required."

    def on_wake(self) -> None:
        with self._lock:
            self.wake_events += 1
            self.armed_until = time.time() + self._cfg_timeout()

    def request_interrupt(self) -> None:
        with self._lock:
            self.interrupt_requested = True

    def clear_interrupt(self) -> bool:
        with self._lock:
            was = self.interrupt_requested
            self.interrupt_requested = False
            return was

    def status(self) -> dict:
        with self._lock:
            armed = self.conversation_mode or (time.time() < self.armed_until)
            return {
                "conversation_mode": self.conversation_mode,
                "armed": armed,
                "armed_until": self.armed_until,
                "listening": self.listening,
                "speaking": self.speaking,
            }


_SESSION: VoiceSession | None = None
_LOCK = threading.Lock()


def get_session() -> VoiceSession:
    global _SESSION
    with _LOCK:
        if _SESSION is None:
            _SESSION = VoiceSession()
            # Mirror config conversation_mode default
            try:
                import json
                from pathlib import Path
                voice = json.loads(
                    (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
                ).get("voice") or {}
                if voice.get("conversation_mode"):
                    _SESSION.conversation_mode = True
            except Exception:
                pass
        return _SESSION
