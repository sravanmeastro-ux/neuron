"""Speaking styles — rewrite/light wrap by mode + emotion."""

from __future__ import annotations

import re

from neuron.personality.emotion import Emotion
from neuron.personality.modes import ModeSpec


def apply_speaking_style(
    say: str,
    mode: ModeSpec,
    emotion: Emotion,
    *,
    name: str = "NEURON",
) -> str:
    text = (say or "").strip()
    if not text:
        return text

    # Strip duplicate assistant name spam
    text = re.sub(rf"^(?:{re.escape(name)}\s*[:\-–]\s*)+", "", text, flags=re.I)

    if mode.id == "professional":
        text = _professional(text, emotion)
    elif mode.id == "friendly":
        text = _friendly(text, emotion)
    else:
        text = _jarvis(text, emotion)

    # Soft length cap for voice
    if len(text) > 420:
        text = text[:417].rstrip() + "…"
    return text.strip()


def _professional(text: str, emotion: Emotion) -> str:
    # Remove casual fillers
    text = re.sub(r"\b(gonna|wanna|hey+|lol|haha)\b", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if emotion.label == "frustrated":
        return f"Understood. {text}" if not text.lower().startswith("understood") else text
    if emotion.label == "urgent":
        return text if text.endswith(".") else text.rstrip("!") + "."
    # Ensure formal ending
    if text and text[-1] not in ".!?":
        text += "."
    return text[0].upper() + text[1:] if text else text


def _friendly(text: str, emotion: Emotion) -> str:
    if emotion.label == "grateful" and "welcome" not in text.lower():
        return f"{text.rstrip('.')} - happy to help!"
    if emotion.label == "frustrated":
        return f"No worries — {text[0].lower() + text[1:] if text else text}"
    if emotion.label == "happy":
        return text if "!" in text else text.rstrip(".") + "!"
    return text


def _jarvis(text: str, emotion: Emotion) -> str:
    low = text.lower()
    # Occasional Sir address for greetings / done
    if emotion.label == "grateful" and "sir" not in low:
        return f"You're welcome, Sir. {text}" if not low.startswith("you") else text
    if emotion.label == "frustrated":
        if not low.startswith(("of course", "certainly", "right away")):
            return f"Of course. {text}"
    if emotion.label == "urgent":
        if "right away" not in low and "immediately" not in low:
            return f"Right away. {text}"
    return text
