"""Detect computer-use style goals (vs single Category A commands)."""

from __future__ import annotations

import re

_CU = re.compile(
    r"\b("
    r"book\s+(?:a\s+)?(?:train|flight|ticket)|"
    r"download\s+blender|"
    r"fill\s+(?:this\s+)?(?:form|out)|"
    r"upload\s+(?:this\s+)?file|"
    r"open\s+discord\b.+\b(?:send|message)|"
    r"send\s+(?:this\s+)?message\b.+\bdiscord|"
    r"navigate\s+(?:to\s+)?settings|"
    r"open\s+settings|"
    r"click\s+(?:the\s+)?[\w ]+|"
    r"drag\s+.+\s+to\b|"
    r"computer\s+use|"
    r"use\s+(?:the\s+)?(?:computer|screen|mouse)|"
    r"operate\s+(?:the\s+)?(?:app|window|application)"
    r")\b",
    re.I,
)

_SINGLE = re.compile(
    r"^(?:mute|unmute|volume\s+(?:up|down)|copy|paste|undo|"
    r"open\s+[\w .+-]{1,40}|close\s+[\w .+-]{1,40})"
    r"(?:\s+please)?[.!?]?$",
    re.I,
)


def looks_like_computer_use(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) < 8:
        return False
    if _SINGLE.match(t):
        return False
    return bool(_CU.search(t))
