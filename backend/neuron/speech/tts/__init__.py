"""Modular local TTS (Phase 7)."""

from neuron.speech.tts.engine import get_tts, is_speaking, speak, status, stop_speaking
from neuron.speech.tts.base import SpeakResult

__all__ = [
    "speak",
    "stop_speaking",
    "is_speaking",
    "get_tts",
    "status",
    "SpeakResult",
]
