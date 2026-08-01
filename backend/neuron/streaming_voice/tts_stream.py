"""Streaming TTS helpers — wraps existing TTSEngine.speak_stream_events."""

from __future__ import annotations

import time
from typing import Iterator

from neuron.streaming_voice.config import streaming_tts_enabled


def stream_tts(text: str) -> Iterator[dict]:
    """Yield tts_chunk / tts_interrupted / tts_done events with latency meta."""
    if not (text or "").strip():
        yield {"type": "tts_done", "interrupted": False, "tts_ms": 0.0}
        return
    t0 = time.perf_counter()
    first_chunk_ms = None
    try:
        from neuron.speech.tts import get_tts
        engine = get_tts()
        if streaming_tts_enabled() and hasattr(engine, "speak_stream_events"):
            for ev in engine.speak_stream_events(text):
                if ev.get("type") == "tts_chunk" and first_chunk_ms is None:
                    first_chunk_ms = round((time.perf_counter() - t0) * 1000, 2)
                    ev = dict(ev)
                    ev["tts_first_chunk_ms"] = first_chunk_ms
                yield ev
            yield {
                "type": "tts_metrics",
                "tts_ms": round((time.perf_counter() - t0) * 1000, 2),
                "tts_first_chunk_ms": first_chunk_ms,
            }
            return
        # Fallback: blocking speak
        from neuron.speech.tts import speak
        result = speak(text)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        yield {
            "type": "tts_ready",
            "engine": getattr(result, "engine", "browser"),
            "audio_url": getattr(result, "audio_url", None),
            "tts_ms": ms,
        }
        yield {"type": "tts_done", "interrupted": bool(getattr(result, "interrupted", False)), "tts_ms": ms}
    except Exception as exc:
        yield {"type": "tts_error", "error": str(exc)}
        yield {"type": "tts_done", "interrupted": False, "error": str(exc)}
