"""Deterministic intent/family parsing — LLM never executes tools."""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.context.types import GoalCandidate, IntentFamily, ParsedUtterance

_ORDINAL = {
    "first": 1,
    "1st": 1,
    "number one": 1,
    "option one": 1,
    "second": 2,
    "2nd": 2,
    "number two": 2,
    "option two": 2,
    "third": 3,
    "3rd": 3,
    "last": -1,
    "next": 1,  # relative; consumer may adjust
    "previous": -2,
}


def parse_ordinal(text: str) -> int | None:
    t = (text or "").lower().strip()
    for k, v in _ORDINAL.items():
        if re.search(rf"\b{re.escape(k)}\b", t):
            return v
    m = re.search(r"\b(?:the\s+)?(\d+)(?:st|nd|rd|th)?\s+(?:one|result|video|item)?\b", t)
    if m:
        return int(m.group(1))
    return None


def classify_family(text: str) -> IntentFamily:
    t = (text or "").lower().strip()
    if not t:
        return IntentFamily.UNKNOWN
    if re.search(r"\b(?:neuron\s+)?(?:stop|cancel)\b", t) or t in ("stop", "cancel"):
        return IntentFamily.STOP
    if re.match(r"^(?:yes|yeah|yep|confirm|proceed|ok|okay)\b", t):
        return IntentFamily.CONFIRMATION
    if re.match(r"^(?:open|start|launch|bring)\b", t):
        return IntentFamily.OPEN
    if re.match(r"^(?:close|quit|exit)\b", t) and "fullscreen" not in t:
        return IntentFamily.CLOSE
    if re.match(r"^(?:focus|switch\s+to|bring\s+to\s+front)\b", t):
        return IntentFamily.FOCUS
    if re.search(r"\b(?:move|put|send)\b.+\bmonitor\b|\bother\s+monitor\b", t):
        return IntentFamily.MOVE
    if re.match(r"^(?:search|find|look\s+up)\b", t):
        return IntentFamily.SEARCH
    if re.match(r"^(?:go\s+to|navigate|open\s+youtube|open\s+website)\b", t):
        return IntentFamily.NAVIGATE
    if re.match(r"^(?:play|watch)\b", t):
        return IntentFamily.PLAY
    if re.match(r"^(?:pause|resume)\b", t):
        return IntentFamily.PAUSE
    if "fullscreen" in t:
        return IntentFamily.FULLSCREEN
    if re.match(r"^(?:click|press|tap)\b", t):
        return IntentFamily.CLICK
    if re.match(r"^(?:type|enter|write)\b", t):
        return IntentFamily.TYPE
    if re.match(r"^(?:scroll|swipe)\b", t):
        return IntentFamily.SCROLL
    if re.search(r"\b(?:mute|unmute|volume)\b", t):
        return IntentFamily.VOLUME
    if re.match(r"^(?:the\s+)?(?:first|second|third|last|next|previous|chrome|other)\b", t):
        return IntentFamily.SELECT
    return IntentFamily.UNKNOWN


def extract_args(text: str, family: IntentFamily) -> dict[str, Any]:
    t = (text or "").strip()
    args: dict[str, Any] = {}
    mon = re.search(r"\bmonitor\s+(\d+|other|left|right|main|second)\b", t, re.I)
    if mon:
        args["monitor"] = mon.group(1).lower()
    if family is IntentFamily.OPEN:
        m = re.match(r"^(?:open|start|launch|bring\s+up)\s+(.+?)(?:\s+on\s+monitor\b.*)?$", t, re.I)
        if m:
            args["name"] = re.sub(r"\s+on\s+monitor\s+\S+$", "", m.group(1), flags=re.I).strip()
    if family is IntentFamily.SEARCH:
        m = re.match(r"^(?:search(?:\s+for)?|find|look\s+up)\s+(.+)$", t, re.I)
        if m:
            args["query"] = m.group(1).strip()
    if family is IntentFamily.NAVIGATE:
        m = re.match(r"^(?:go\s+to|navigate\s+to)\s+(.+)$", t, re.I)
        if m:
            args["site"] = m.group(1).strip()
    if family is IntentFamily.PLAY:
        ord_n = parse_ordinal(t)
        if ord_n is not None:
            args["ordinal"] = ord_n
        m = re.match(r"^play\s+(.+)$", t, re.I)
        if m and "ordinal" not in args:
            args["query"] = m.group(1).strip()
    if family is IntentFamily.MOVE:
        m = re.search(r"(?:move|put|send)\s+(.+?)\s+(?:to|on)\s+monitor", t, re.I)
        if m:
            args["name"] = m.group(1).strip()
    if family is IntentFamily.SELECT:
        ord_n = parse_ordinal(t)
        if ord_n is not None:
            args["ordinal"] = ord_n
        if re.search(r"\bchrome\b", t, re.I):
            args["choice"] = "chrome"
        if re.search(r"\bother\b", t, re.I):
            args["choice"] = args.get("choice") or "other"
    return args


def build_goal(parsed: ParsedUtterance) -> GoalCandidate:
    text = parsed.canonical or parsed.cleaned or parsed.raw
    if parsed.compound_parts and len(parsed.compound_parts) >= 2:
        family = IntentFamily.MULTI_STEP_GOAL
        return GoalCandidate(
            text=text,
            normalized=text,
            intent_family=family,
            args={"parts": list(parsed.compound_parts)},
            confidence=0.75,
            multi_step=True,
            source="deterministic",
        )
    family = classify_family(text)
    args = extract_args(text, family)
    if parsed.negation:
        args["negated"] = True
        if parsed.negation_target:
            args["negation_target"] = parsed.negation_target
    conf = 0.85 if family not in (IntentFamily.UNKNOWN, IntentFamily.FOLLOW_UP) else 0.4
    if parsed.correction_final:
        conf = min(conf + 0.05, 0.95)
    return GoalCandidate(
        text=text,
        normalized=text,
        intent_family=family,
        args=args,
        confidence=conf,
        multi_step=False,
        source="correction" if parsed.correction_final else "deterministic",
    )


__all__ = ["parse_ordinal", "classify_family", "extract_args", "build_goal"]
