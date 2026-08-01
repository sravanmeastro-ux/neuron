"""Personality modes — professional, friendly, Iron Man JARVIS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModeSpec:
    id: str
    label: str
    speaking_style: str
    voice_style: str  # calm | warm | crisp
    humor: str  # none | light | dry
    rate_bias: int  # TTS rate delta
    prefix_ok: bool = True
    system_blurb: str = ""


MODES: dict[str, ModeSpec] = {
    "professional": ModeSpec(
        id="professional",
        label="Professional",
        speaking_style="clear, formal, concise, no slang",
        voice_style="calm",
        humor="none",
        rate_bias=-10,
        system_blurb="Speak formally and precisely. Prefer short declarative sentences. No jokes.",
    ),
    "friendly": ModeSpec(
        id="friendly",
        label="Friendly",
        speaking_style="warm, encouraging, conversational",
        voice_style="warm",
        humor="light",
        rate_bias=5,
        system_blurb="Be warm and approachable. Light encouragement is fine. Keep it brief.",
    ),
    "jarvis": ModeSpec(
        id="jarvis",
        label="Iron Man JARVIS",
        speaking_style="dry British wit, loyal, confident, concise",
        voice_style="crisp",
        humor="dry",
        rate_bias=0,
        system_blurb=(
            "Channel Iron Man's JARVIS: witty, confident, loyal, concise. "
            "Dry British humor. Never rude. Address the user as Sir when it fits."
        ),
    ),
}

ALIASES = {
    "pro": "professional",
    "formal": "professional",
    "business": "professional",
    "casual": "friendly",
    "warm": "friendly",
    "ironman": "jarvis",
    "iron man": "jarvis",
    "j.a.r.v.i.s": "jarvis",
    "tony": "jarvis",
}


def normalize_mode(name: str | None) -> str:
    n = (name or "").strip().lower()
    if not n:
        return "jarvis"
    n = ALIASES.get(n, n)
    if n in MODES:
        return n
    return "jarvis"


def get_mode(name: str | None = None) -> ModeSpec:
    return MODES[normalize_mode(name)]
