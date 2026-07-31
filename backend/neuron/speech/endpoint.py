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
    "like and subscribe", "don't forget to subscribe", "smash that like",
    "see you in the next video", "thanks for watching guys",
    "thanks", "thank you so much", "thank you guys", "bye", "goodbye",
    "you're welcome", "you are welcome",
}

# Cinematic / YouTube bleed often looks like dialogue, not PC commands
_MEDIA_BLEED = re.compile(
    r"(?i)\b("
    r"thanks for watching|subscribe|like and subscribe|in the next video|"
    r"we'll lose|i love you|i'm sorry|you'?ve built|full screen the video|"
    r"coming up next|sponsored by|use code|link in (the )?description|"
    r"leave a comment|hit the bell|smash (?:the )?like"
    r")\b"
)

_CMD_HINT = re.compile(
    r"(?i)\b("
    r"open|close|launch|quit|focus|minimize|maximize|move|switch|"
    r"search|find|play|pause|stop|skip|mute|unmute|volume|"
    r"click|type|press|scroll|"
    r"neuron|jarvis|confirm|cancel|wait|go to|navigate"
    r")\b"
)

# Stronger verbs — used to exempt media-bleed phrases (fullscreen alone is too weak)
_STRONG_CMD = re.compile(
    r"(?i)\b("
    r"open|close|launch|quit|focus|minimize|maximize|move|"
    r"search|find|pause|stop|skip|mute|unmute|volume|"
    r"click|type|press|neuron|jarvis|confirm|cancel"
    r")\b"
)


@dataclass
class GateResult:
    accept: bool
    text: str
    reason: str = ""


def clean_transcript(text: str) -> str:
    text = (text or "").strip()
    # Whisper sometimes wraps polite bleed as "(Thank you)"
    text = re.sub(r"[()\[\]{}]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t.,;:!?\"'")


def is_short_safe_command(text: str) -> bool:
    """Commands that should work even while speakers are loud (no wake needed)."""
    low = clean_transcript(text).lower()
    if not low:
        return False
    return bool(
        re.fullmatch(
            r"(?:please\s+)?(?:"
            r"scroll(?:\s+the\s+page)?\s+(?:up|down)"
            r"|scroll(?:\s+up|\s+down)?"
            r"|page\s+(?:up|down)"
            r"|volume\s+(?:up|down)"
            r"|mute|unmute|pause|play|stop(?:\s+talking)?"
            r"|skip(?:\s+the|\s+this|\s+that)?\s+(?:ad|ads|add|adds|sad)"
            r"|cancel|never\s+mind"
            r")",
            low,
        )
    )


def is_complete_command(text: str, *, min_chars: int = 3, min_words: int = 1) -> GateResult:
    """Return whether this final transcript should run through the brain.

    Partial accidental fragments (trailing 'and'/'the', too short, junk) are rejected.
    """
    raw = clean_transcript(text)
    if not raw:
        return GateResult(False, "", "empty")
    low = raw.lower().strip(" .")
    # Politeness / YouTube outros — never commands
    if low in _JUNK or low in {"thanks", "thank you so much", "thank you guys", "bye", "goodbye"}:
        return GateResult(False, raw, "junk_or_short")
    if len(low) < min_chars:
        return GateResult(False, raw, "junk_or_short")
    if re.fullmatch(r"thanks?(?:\s+you)?(?:\s+(?:so\s+much|guys|everyone))?", low):
        return GateResult(False, raw, "junk_polite")
    # Critical short voice commands — never reject as incomplete/junk
    if is_short_safe_command(raw) or re.search(
        r"^(?:please\s+)?(?:skip(?:\s+the|\s+this|\s+that)?\s+(?:ad|ads|add|adds|sad)"
        r"|stop(?:\s+talking)?|pause|play|mute|unmute|"
        r"scroll(?:\s+the\s+page)?\s+(?:up|down))\b",
        low,
    ):
        return GateResult(True, raw, "priority_cmd")

    words = [w for w in re.split(r"\s+", raw) if w]
    if len(words) < min_words and len(raw) < 8:
        return GateResult(False, raw, "too_few_words")
    # Trailing incomplete filler — likely cut mid-phrase / VAD too early
    if _TRAILING_INCOMPLETE.search(raw) and len(words) <= 4:
        return GateResult(False, raw, "incomplete_trailing")
    # Single filler word
    if len(words) == 1 and words[0].lower() in _JUNK:
        return GateResult(False, raw, "filler")
    # Obvious YouTube / dialogue bleed (even before media meter)
    if _MEDIA_BLEED.search(raw) and not _STRONG_CMD.search(raw):
        return GateResult(False, raw, "media_bleed_phrase")
    return GateResult(True, raw, "ok")


def looks_like_voice_command(text: str) -> bool:
    """Loose heuristic: transcript mentions a PC-control verb or wake name."""
    raw = clean_transcript(text)
    if not raw:
        return False
    return bool(_CMD_HINT.search(raw) or _STRONG_CMD.search(raw))


def reject_media_bleed(text: str, *, media_loud: bool) -> GateResult | None:
    """When speakers are loud, reject non-command dialogue unless it looks intentional."""
    if not media_loud:
        return None
    raw = clean_transcript(text)
    if not raw:
        return GateResult(False, "", "empty")
    if _MEDIA_BLEED.search(raw):
        return GateResult(False, raw, "media_bleed_phrase")
    # Long dialogue without command verbs → almost certainly speaker bleed
    words = [w for w in re.split(r"\s+", raw) if w]
    if len(words) >= 6 and not looks_like_voice_command(raw):
        return GateResult(False, raw, "media_bleed_long")
    return None


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
