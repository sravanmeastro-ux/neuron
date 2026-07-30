"""Speech package — Phase 6 voice STT + Phase 7 modular TTS."""

from neuron.speech.endpoint import is_complete_command, strip_wake_prefix
from neuron.speech.pipeline import VoicePipeline
from neuron.speech.session import VoiceSession, get_session

__all__ = [
    "VoicePipeline",
    "VoiceSession",
    "get_session",
    "is_complete_command",
    "strip_wake_prefix",
]
