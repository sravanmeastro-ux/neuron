"""Local Piper TTS — thin compatibility wrapper over Phase 7 modular engine."""

from __future__ import annotations

from neuron.speech.tts import engine as tts_engine
from neuron.speech.tts.piper_provider import PiperProvider


def is_piper_available() -> bool:
    return PiperProvider().available()


def speak_to_file(text: str) -> dict:
    """Back-compat for server.py. Prefer neuron.speech.tts.speak()."""
    result = tts_engine.speak(text)
    return result.to_dict()


def status() -> str:
    return tts_engine.status()
