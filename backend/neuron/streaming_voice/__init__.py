"""Production-grade Streaming Voice Engine for NEURON.

Mic → preprocess (noise/echo hooks) → streaming STT (Faster-Whisper via
existing VoicePipeline) → early intent → brain / Task Planner → streaming
LLM / TTS. Modes: continuous, push-to-talk, conversation.
"""

from __future__ import annotations

from neuron.streaming_voice.bridge import create_engine, is_streaming_engine
from neuron.streaming_voice.engine import StreamingVoiceEngine
from neuron.streaming_voice.early_intent import try_early_intent, looks_early_executable
from neuron.streaming_voice.llm_stream import stream_llm
from neuron.streaming_voice.tts_stream import stream_tts
from neuron.streaming_voice.types import ListenMode, StreamEvent, VoiceMetrics

__all__ = [
    "StreamingVoiceEngine",
    "create_engine",
    "is_streaming_engine",
    "try_early_intent",
    "looks_early_executable",
    "stream_llm",
    "stream_tts",
    "ListenMode",
    "StreamEvent",
    "VoiceMetrics",
]
