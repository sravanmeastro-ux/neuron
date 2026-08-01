"""Humor layer — dry JARVIS quips, light friendly jokes; gated by mode."""

from __future__ import annotations

import hashlib
from typing import Any

from neuron.personality.modes import ModeSpec

_JARVIS_OK = [
    "As always, I aim to please.",
    "All part of the service.",
    "Consider it handled.",
    "I do try to make the impossible look routine.",
    "Shall I also prepare a witty status update? On second thought — already done.",
]

_JARVIS_FAIL = [
    "Even genius software has off moments.",
    "A minor setback. Nothing a little ingenuity won't fix.",
    "I regret to report a hiccup in the plan.",
]

_FRIENDLY_OK = [
    "Nice!",
    "That went smoothly.",
    "Boom — done.",
]

_FRIENDLY_FAIL = [
    "Hmm, that didn't quite work.",
    "Almost — let's try another angle next time.",
]


def maybe_quip(
    say: str,
    mode: ModeSpec,
    *,
    acted: bool = True,
    path: str = "",
    seed: str = "",
) -> str:
    if mode.humor == "none":
        return say
    text = (say or "").strip()
    if not text:
        return text
    # Don't quip on confirms / stops / long reports
    low = text.lower()
    if any(x in low for x in ("confirm to run", "say 'confirm'", "__stop", "cancelled")):
        return text
    if len(text) > 280:
        return text
    # Deterministic sparse humor (~35% for jarvis dry, ~25% friendly)
    h = hashlib.md5((seed or text[:40] + path).encode("utf-8")).hexdigest()
    roll = int(h[:2], 16) / 255.0
    threshold = 0.35 if mode.humor == "dry" else 0.25
    if roll > threshold:
        return text
    if mode.humor == "dry":
        pool = _JARVIS_OK if acted else _JARVIS_FAIL
    else:
        pool = _FRIENDLY_OK if acted else _FRIENDLY_FAIL
    idx = int(h[2:4], 16) % len(pool)
    quip = pool[idx]
    if quip.lower() in low:
        return text
    # Append lightly
    if text.endswith((".", "!", "?")):
        return f"{text} {quip}"
    return f"{text}. {quip}"
