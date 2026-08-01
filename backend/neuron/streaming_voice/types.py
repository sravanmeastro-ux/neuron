"""Streaming Voice Engine types and events."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ListenMode(str, Enum):
    CONTINUOUS = "continuous"
    PTT = "ptt"
    CONVERSATION = "conversation"


@dataclass
class StreamEvent:
    """Unified outbound voice event for WS / UI."""

    kind: str  # level|partial|final|wake|rejected|early_intent|tts_chunk|tts_done|mode|metrics
    text: str = ""
    level: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_ws(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.kind, "text": self.text}
        if self.kind == "level" or self.level:
            d["level"] = round(self.level, 3)
        if self.meta:
            d.update(self.meta)
        return d


@dataclass
class VoiceMetrics:
    wake_ms: float = 0.0
    stt_ms: float = 0.0
    vad_ms: float = 0.0
    tts_ms: float = 0.0
    e2e_ms: float = 0.0
    interrupt_ms: float = 0.0
    early_intent_ms: float = 0.0
    samples: dict[str, list[float]] = field(default_factory=dict)

    def record(self, name: str, ms: float) -> None:
        bucket = self.samples.setdefault(name, [])
        bucket.append(float(ms))
        if len(bucket) > 64:
            del bucket[:-64]
        if name == "wake_ms":
            self.wake_ms = ms
        elif name == "stt_ms":
            self.stt_ms = ms
        elif name == "vad_ms":
            self.vad_ms = ms
        elif name == "tts_ms":
            self.tts_ms = ms
        elif name == "e2e_ms":
            self.e2e_ms = ms
        elif name == "interrupt_ms":
            self.interrupt_ms = ms
        elif name == "early_intent_ms":
            self.early_intent_ms = ms

    def summary(self) -> dict[str, Any]:
        def _stats(vals: list[float]) -> dict[str, float]:
            if not vals:
                return {"n": 0, "mean": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
            s = sorted(vals)
            n = len(s)
            return {
                "n": n,
                "mean": round(sum(s) / n, 2),
                "p95": round(s[min(n - 1, int(n * 0.95))], 2),
                "min": round(s[0], 2),
                "max": round(s[-1], 2),
            }

        return {
            "last": {
                "wake_ms": self.wake_ms,
                "stt_ms": self.stt_ms,
                "vad_ms": self.vad_ms,
                "tts_ms": self.tts_ms,
                "e2e_ms": self.e2e_ms,
                "interrupt_ms": self.interrupt_ms,
                "early_intent_ms": self.early_intent_ms,
            },
            "series": {k: _stats(v) for k, v in self.samples.items()},
        }

    def to_dict(self) -> dict[str, Any]:
        return self.summary()
