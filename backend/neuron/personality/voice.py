"""Voice style hints for TTS (rate / style tags) — does not rewrite TTS cores."""

from __future__ import annotations

from typing import Any

from neuron.personality.emotion import Emotion
from neuron.personality.modes import ModeSpec


def voice_hints(mode: ModeSpec, emotion: Emotion) -> dict[str, Any]:
    """Hints consumers (server/TTS) may apply; safe defaults."""
    rate = 185 + int(mode.rate_bias)
    if emotion.label == "urgent":
        rate += 15
    elif emotion.label in ("sad", "frustrated"):
        rate -= 10
    elif emotion.label == "happy":
        rate += 5
    rate = max(140, min(220, rate))
    return {
        "style": mode.voice_style,  # calm | warm | crisp
        "mode": mode.id,
        "emotion": emotion.label,
        "rate": rate,
        "speaking_style": mode.speaking_style,
    }
