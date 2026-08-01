"""Bridge helpers for server WebSocket wiring."""

from __future__ import annotations

from typing import Any

from neuron.streaming_voice.config import streaming_enabled
from neuron.streaming_voice.engine import StreamingVoiceEngine


def create_engine() -> StreamingVoiceEngine | Any:
    """Create StreamingVoiceEngine, or fall back to VoicePipeline."""
    if not streaming_enabled():
        from neuron.speech.pipeline import VoicePipeline
        from neuron.speech.session import get_session
        return VoicePipeline(get_session())
    return StreamingVoiceEngine()


def is_streaming_engine(obj: Any) -> bool:
    return isinstance(obj, StreamingVoiceEngine)
