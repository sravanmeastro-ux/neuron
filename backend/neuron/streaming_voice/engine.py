"""Streaming Voice Engine — production orchestration over existing speech stack.

Microphone PCM → preprocess → VoicePipeline (VAD/STT/wake/endpoint) →
early intent → (server) Task Planner / brain → streaming LLM/TTS.

Does not modify FastIntentRouter, Semantic, Screen, Task Planning, or latency
VAD thresholds — it wraps and extends.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from neuron.streaming_voice.audio_hooks import get_audio_chain
from neuron.streaming_voice import config as cfg_mod
from neuron.streaming_voice.early_intent import try_early_intent, was_early_fired
from neuron.streaming_voice.modes import ModeController
from neuron.streaming_voice.types import StreamEvent, VoiceMetrics


class StreamingVoiceEngine:
    """Per-websocket streaming voice controller."""

    def __init__(self, pipeline=None, session=None):
        if pipeline is None:
            from neuron.speech.pipeline import VoicePipeline
            from neuron.speech.session import get_session
            session = session or get_session()
            pipeline = VoicePipeline(session)
        self.pipeline = pipeline
        self.session = session or getattr(pipeline, "session", None)
        self.modes = ModeController()
        self.metrics = VoiceMetrics()
        self.audio = get_audio_chain()
        self._busy = False
        self._utterance_t0 = 0.0
        self._wake_t0 = 0.0
        self._interrupt_t0 = 0.0
        self._last_early_text = ""

    # ---- compat with VoicePipeline surface used by server --------------
    @property
    def assembler(self):
        return self.pipeline.assembler

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        try:
            self.pipeline.set_busy(busy)
        except Exception:
            pass

    def set_muted(self, muted: bool) -> None:
        self.pipeline.set_muted(muted)

    def set_listen_mode(self, mode: str) -> str:
        msg = self.modes.set_mode(mode)
        return msg

    def ptt(self, down: bool) -> dict[str, Any]:
        self.modes.on_ptt(down)
        # Soft mute when PTT up
        if self.modes.mode.value == "ptt":
            self.set_muted(not down)
        return self.modes.snapshot()

    def push_pcm(self, pcm_f32: np.ndarray) -> list[StreamEvent]:
        """Streaming mic frame → events (never calls brain except early intent)."""
        out: list[StreamEvent] = []
        if pcm_f32 is None or len(pcm_f32) == 0:
            return out

        # Mode gate (PTT)
        if not self.modes.should_listen():
            # Still emit silence levels for UI? skip ASR
            if self.modes.mode.value == "ptt" and not self.modes.ptt_down:
                return out

        # Preprocess: noise suppression + echo cancellation hooks
        pcm = self.audio.process(np.asarray(pcm_f32, dtype=np.float32))

        t_push = time.perf_counter()
        raw_events = self.pipeline.push_pcm(pcm)
        for ev in raw_events:
            kind = ev.kind
            meta = dict(ev.meta or {})
            if kind == "level":
                out.append(StreamEvent(kind="level", level=ev.level, meta=meta))
                # Track barge-in interrupt latency start
                if self._busy and ev.level >= cfg_mod.barge_in_level():
                    if not self._interrupt_t0:
                        self._interrupt_t0 = time.perf_counter()
                continue

            if kind == "wake":
                self._wake_t0 = time.perf_counter()
                self.modes.arm(float(cfg_mod.voice_cfg().get("conversation_timeout_seconds", 45) or 45))
                out.append(StreamEvent(kind="wake", text=ev.text or "Neuron", meta=meta))
                continue

            if kind == "partial" and ev.text:
                out.append(StreamEvent(kind="partial", text=ev.text, meta=meta))
                # Early intent on partial
                early = try_early_intent(ev.text, busy=self._busy)
                if early and early.get("ok"):
                    self._last_early_text = early.get("text") or ev.text
                    self.metrics.record("early_intent_ms", float(early.get("early_intent_ms") or 0))
                    out.append(
                        StreamEvent(
                            kind="early_intent",
                            text=early.get("say") or "",
                            meta=early,
                        )
                    )
                continue

            if kind == "rejected":
                out.append(StreamEvent(kind="rejected", text=ev.text or "", meta=meta))
                continue

            if kind == "final" and ev.text:
                # Skip re-execution if early intent already handled this
                if was_early_fired(ev.text):
                    meta["skipped_early_duplicate"] = True
                    out.append(
                        StreamEvent(
                            kind="final",
                            text=ev.text,
                            meta={**meta, "execute": False},
                        )
                    )
                    continue
                if meta.get("stt_ms"):
                    self.metrics.record("stt_ms", float(meta["stt_ms"]))
                if meta.get("vad_ms"):
                    self.metrics.record("vad_ms", float(meta["vad_ms"]))
                if self._wake_t0:
                    self.metrics.record(
                        "wake_ms",
                        round((time.perf_counter() - self._wake_t0) * 1000, 2),
                    )
                    self._wake_t0 = 0.0
                meta["execute"] = True
                meta["push_ms"] = round((time.perf_counter() - t_push) * 1000, 2)
                out.append(StreamEvent(kind="final", text=ev.text, meta=meta))
                self.modes.arm(float(cfg_mod.voice_cfg().get("conversation_timeout_seconds", 45) or 45))
                continue

            out.append(StreamEvent(kind=kind, text=ev.text or "", level=ev.level, meta=meta))
        return out

    def note_interrupt(self) -> float:
        """Record interruption latency (call when barge-in fires)."""
        if self._interrupt_t0:
            ms = round((time.perf_counter() - self._interrupt_t0) * 1000, 2)
            self.metrics.record("interrupt_ms", ms)
            self._interrupt_t0 = 0.0
            return ms
        return 0.0

    def note_e2e(self, ms: float) -> None:
        self.metrics.record("e2e_ms", float(ms))

    def note_tts(self, ms: float) -> None:
        self.metrics.record("tts_ms", float(ms))

    def status(self) -> dict[str, Any]:
        return {
            "engine": "streaming_voice",
            "enabled": cfg_mod.streaming_enabled(),
            "mode": self.modes.snapshot(),
            "metrics": self.metrics.summary(),
            "early_intent": cfg_mod.early_intent_enabled(),
            "echo_cancellation": cfg_mod.echo_cancellation_enabled(),
            "noise_suppression": cfg_mod.noise_suppression_enabled(),
            "streaming_tts": cfg_mod.streaming_tts_enabled(),
        }
