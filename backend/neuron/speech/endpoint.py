"""Utterance endpointing + rejection of partial / accidental transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass


_TRAILING_INCOMPLETE = re.compile(
    r"\b(and|or|the|a|an|to|for|with|of|in|on|at|my|please|um+|uh+|so)\s*$",
    re.I,
)
_JUNK = {
    "thank you", "thanks for watching", "subscribe", "you", "the", "a", "um", "uh",
    "thank you for watching", "mbc 뉴스", "www", "subtitle", "subtitles by",
    "amara.org", ".", "okay", "ok", "hmm", "huh", "ah", "oh",
}


@dataclass
class GateResult:
    accept: bool
    text: str
    reason: str = ""


def clean_transcript(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t.,;:!?")


def is_complete_command(text: str, *, min_chars: int = 3, min_words: int = 1) -> GateResult:
    """Return whether this final transcript should run through the brain.

    Partial accidental fragments (trailing 'and'/'the', too short, junk) are rejected.
    """
    raw = clean_transcript(text)
    if not raw:
        return GateResult(False, "", "empty")
    low = raw.lower().strip(" .")
    if low in _JUNK or len(low) < min_chars:
        return GateResult(False, raw, "junk_or_short")
    words = [w for w in re.split(r"\s+", raw) if w]
    if len(words) < min_words and len(raw) < 8:
        return GateResult(False, raw, "too_few_words")
    # Trailing incomplete filler — likely cut mid-phrase / VAD too early
    if _TRAILING_INCOMPLETE.search(raw) and len(words) <= 4:
        return GateResult(False, raw, "incomplete_trailing")
    # Single filler word
    if len(words) == 1 and words[0].lower() in _JUNK:
        return GateResult(False, raw, "filler")
    return GateResult(True, raw, "ok")


def strip_wake_prefix(text: str, names: tuple[str, ...] = ("neuron", "jarvis", "assistant")) -> str:
    """'Neuron, open chrome' / 'Neuron.' → 'open chrome' / ''."""
    t = clean_transcript(text)
    if not t:
        return ""
    # Standalone wake
    low = t.lower().rstrip(".!,")
    if low in names:
        return ""
    pat = re.compile(
        r"^(?:hey |hi |hello |ok |okay )?(?:" + "|".join(re.escape(n) for n in names) + r")\b[\s,.\-:]*",
        re.I,
    )
    out = pat.sub("", t, count=1).strip(" ,.-")
    return out
