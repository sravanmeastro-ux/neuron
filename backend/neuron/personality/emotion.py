"""Light lexical emotion detection from user text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Emotion:
    label: str  # neutral | happy | frustrated | urgent | curious | grateful | sad
    score: float
    cues: list[str]

    def to_dict(self) -> dict:
        return {"label": self.label, "score": self.score, "cues": list(self.cues)}


_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("grateful", re.compile(r"\b(thanks|thank you|appreciate|grateful)\b", re.I), 0.85),
    ("frustrated", re.compile(r"\b(damn|argh|annoyed|frustrated|stupid|broken|why (is|won.?t)|again!?)\b", re.I), 0.8),
    ("urgent", re.compile(r"\b(urgent|asap|immediately|right now|hurry|quick!?|now!?)\b", re.I), 0.85),
    ("happy", re.compile(r"\b(great|awesome|love|wonderful|perfect|nice|yay|excellent)\b", re.I), 0.7),
    ("curious", re.compile(r"\b(what|why|how|curious|wonder|explain|tell me)\b", re.I), 0.55),
    ("sad", re.compile(r"\b(sad|upset|disappointed|sorry|unfortunately)\b", re.I), 0.7),
]


def detect_emotion(text: str) -> Emotion:
    raw = (text or "").strip()
    if not raw:
        return Emotion("neutral", 0.0, [])
    best = Emotion("neutral", 0.2, [])
    for label, pat, score in _PATTERNS:
        m = pat.search(raw)
        if m and score >= best.score:
            best = Emotion(label, score, [m.group(0)])
    # Exclamation / caps urgency bump
    if raw.endswith("!") and best.label == "neutral":
        best = Emotion("urgent", 0.5, ["!"])
    if raw.isupper() and len(raw) > 4:
        best = Emotion("frustrated", max(best.score, 0.75), best.cues + ["CAPS"])
    return best
