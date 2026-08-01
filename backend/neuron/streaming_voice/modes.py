"""Listen mode controller — continuous / push-to-talk / conversation."""

from __future__ import annotations

import time
from typing import Any

from neuron.streaming_voice.config import listen_mode_default
from neuron.streaming_voice.types import ListenMode


class ModeController:
    def __init__(self, mode: str | None = None):
        raw = (mode or listen_mode_default() or "continuous").lower()
        try:
            self.mode = ListenMode(raw)
        except ValueError:
            self.mode = ListenMode.CONTINUOUS
        self.ptt_down = False
        self._armed_until = 0.0

    def set_mode(self, mode: str) -> str:
        raw = (mode or "").strip().lower()
        if raw in ("push_to_talk", "push-to-talk", "ptt"):
            raw = "ptt"
        if raw in ("hands_free", "hands-free", "always"):
            raw = "continuous"
        try:
            self.mode = ListenMode(raw)
        except ValueError:
            return f"Unknown listen mode {mode!r}. Use continuous, ptt, or conversation."
        if self.mode == ListenMode.CONVERSATION:
            try:
                import voice_mode
                voice_mode.set_conversation_mode(True)
            except Exception:
                pass
            self.arm(45.0)
        return f"Listen mode: {self.mode.value}."

    def arm(self, seconds: float = 45.0) -> None:
        self._armed_until = time.time() + float(seconds)

    def on_ptt(self, down: bool) -> None:
        self.ptt_down = bool(down)
        if down:
            self.arm(2.0)

    def should_listen(self) -> bool:
        if self.mode == ListenMode.CONTINUOUS:
            return True
        if self.mode == ListenMode.PTT:
            return bool(self.ptt_down)
        # conversation: listen while armed or ptt
        if self.ptt_down:
            return True
        return time.time() <= self._armed_until

    def snapshot(self) -> dict[str, Any]:
        return {
            "listen_mode": self.mode.value,
            "ptt_down": self.ptt_down,
            "armed": time.time() <= self._armed_until,
            "should_listen": self.should_listen(),
        }
