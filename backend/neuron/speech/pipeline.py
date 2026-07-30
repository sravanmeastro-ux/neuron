"""Phase 6 voice pipeline — VAD stream → (partial ASR) → endpoint → gate → text.

Does NOT call the brain. Server feeds finals into brain.handle_command.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

import stt
from neuron.speech.endpoint import is_complete_command
from neuron.speech.session import VoiceSession, get_session
from neuron.speech import wake as wake_mod


SAMPLE_RATE = stt.SAMPLE_RATE


@dataclass
class VoiceEvent:
    kind: str  # partial | final | rejected | wake | level
    text: str = ""
    level: float = 0.0
    meta: dict | None = None


class VoicePipeline:
    """Stateful per-websocket voice listener."""

    def __init__(self, session: VoiceSession | None = None):
        self.assembler = stt.UtteranceAssembler()
        self.engine = stt.get_engine()
        self.session = session or get_session()
        self._last_partial_at = 0.0
        self._partial_interval = float(self._cfg().get("partial_interval_seconds", 0.85) or 0.85)
        self._oww_buf = np.zeros(0, dtype=np.float32)

    def _cfg(self) -> dict:
        try:
            import json
            from pathlib import Path
            return json.loads(
                (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
            ).get("voice", {}) or {}
        except Exception:
            return {}

    def set_muted(self, muted: bool) -> None:
        self.assembler.set_muted(muted)

    def push_pcm(self, pcm_f32: np.ndarray) -> list[VoiceEvent]:
        """Feed 16 kHz float32 mono. Returns zero or more events (never executes)."""
        events: list[VoiceEvent] = []
        if pcm_f32 is None or len(pcm_f32) == 0:
            return events

        level = self.assembler.level(pcm_f32)
        events.append(VoiceEvent(kind="level", level=level))

        # Optional openWakeWord on rolling buffer (when wake required)
        vcfg = self._cfg()
        if vcfg.get("openwakeword_enabled") and wake_mod.openwakeword_available():
            self._oww_buf = np.concatenate([self._oww_buf, pcm_f32])[-SAMPLE_RATE * 2 :]
            if len(self._oww_buf) >= SAMPLE_RATE and wake_mod.pcm_triggered_wake(self._oww_buf[-SAMPLE_RATE:]):
                self.session.on_wake()
                events.append(VoiceEvent(kind="wake", text="Neuron", meta={"source": "openwakeword"}))
                self._oww_buf = np.zeros(0, dtype=np.float32)

        clip = self.assembler.push(pcm_f32)

        # Chunked / partial transcription while speaking (do NOT execute)
        if self.assembler._in_speech and self.engine.is_enabled():
            now = time.time()
            if now - self._last_partial_at >= self._partial_interval:
                self._last_partial_at = now
                buf = self.assembler._buf
                if buf is not None and len(buf) >= SAMPLE_RATE * 0.6:
                    try:
                        partial = self.engine.transcribe_partial(buf.copy())
                        if partial and partial != self.session.last_partial:
                            self.session.last_partial = partial
                            events.append(VoiceEvent(kind="partial", text=partial))
                    except Exception:
                        pass

        if clip is None:
            return events

        # Final utterance — full transcription + completeness gate
        text = self.engine.transcribe(clip) if self.engine.is_enabled() else ""
        gate = is_complete_command(text)
        if not gate.accept:
            events.append(VoiceEvent(kind="rejected", text=gate.text, meta={"reason": gate.reason}))
            return events

        # Wake / conversation gating (still no brain call)
        try:
            import voice_mode
            wake_req = voice_mode.wake_word_required()
        except Exception:
            wake_req = False

        decision = wake_mod.process_utterance(
            gate.text,
            wake_required=wake_req,
            conversation_armed=self.session.is_armed() or self.session.conversation_mode,
        )
        if decision.get("wake_only"):
            self.session.on_wake()
            events.append(VoiceEvent(kind="wake", text="Neuron", meta={"source": "transcript"}))
            return events
        if not decision.get("allow"):
            events.append(VoiceEvent(kind="rejected", text=gate.text, meta={"reason": "wake_gate"}))
            return events

        final_text = (decision.get("text") or gate.text).strip()
        if not final_text:
            return events

        if decision.get("armed_by_wake"):
            self.session.on_wake()
        # Re-arm conversation window after a real command
        if self.session.conversation_mode or self.session.is_armed():
            self.session.arm()

        self.session.last_final = final_text
        self.session.last_partial = ""
        events.append(VoiceEvent(kind="final", text=final_text, meta={"raw": gate.text}))
        return events
