"""Intent understanding — NLU + voice recipes → structured Intent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import nlu


@dataclass
class Intent:
    raw: str
    normalized: str
    kind: str = "unknown"  # recipe | deterministic | llm | chat | stop
    action: str = ""
    args: dict = field(default_factory=dict)
    confidence: float = 0.0


def understand(raw: str) -> Intent:
    _nlu = nlu.understand(raw)
    text = _nlu.get("canonical") or _nlu.get("cleaned") or (raw or "").strip().lower()
    intent = Intent(raw=raw or "", normalized=text)

    if not text:
        intent.kind = "empty"
        return intent

    import re
    try:
        from neuron.speech.interrupt import is_stop_phrase
        if is_stop_phrase(text):
            intent.kind = "stop"
            return intent
    except Exception:
        if re.search(
            r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron|"
            r"(?:hey\s+)?neuron[,.]?\s+stop)\b|^(?:please\s+)?stop[.!]?$",
            text,
            re.I,
        ):
            intent.kind = "stop"
            return intent

    # Learned procedure match → run_procedure (not while teaching / learning)
    try:
        from neuron.learning import procedures as proc_mod
        if not re.search(r"\b(learn|teach|record|watch me)\b", text, re.I):
            hit = proc_mod.match(text)
            if hit:
                intent.kind = "recipe"
                intent.action = "run_procedure"
                intent.args = {"id": hit.get("id") or ""}
                intent.confidence = 0.92
                return intent
    except Exception:
        pass

    # Voice recipe match → deterministic tool
    try:
        import voice_recipes
        recipe = voice_recipes.match(text)
        if recipe and recipe.get("action"):
            intent.kind = "recipe"
            intent.action = recipe["action"]
            intent.args = dict(recipe.get("args") or {})
            intent.confidence = 0.9
            return intent
    except Exception:
        pass

    # High-reliability YouTube / media — never leave these to the LLM planner
    # (planner often invents page_scroll instead of skip_ad).
    import re
    if re.search(
        r"\b(skip|close|dismiss)\b.{0,24}\b(ad|ads|add|adds|sad)\b"
        r"|\b(ad|ads|add|adds|sad)\b.{0,16}\b(skip|close|dismiss)\b"
        r"|\bskip(?:ping)?(?:\s+the|\s+this|\s+that)?\s+(?:ad|ads|add|adds|sad)\b",
        text,
    ):
        intent.kind = "deterministic"
        intent.action = "skip_ad"
        intent.args = {}
        intent.confidence = 0.95
        return intent

    # Ultra-simple open_app / open_website without LLM
    m = re.fullmatch(r"open ([a-z0-9 .+-]{2,40})", text)
    if m:
        name = m.group(1).strip()
        # Phase 8: deixis / ordinals need context resolver — do not treat as app name
        if re.search(
            r"\b(it|that|this|them|those|these|there|first|second|third|last|one)\b",
            name,
            re.I,
        ):
            intent.kind = "llm"
            intent.confidence = 0.45
            return intent
        websites = {
            "youtube", "yt", "gmail", "google", "maps", "github", "netflix",
            "reddit", "twitter", "facebook", "instagram",
        }
        if name in websites or name.replace(" ", "") in ("youtube",):
            intent.kind = "deterministic"
            intent.action = "open_website"
            intent.args = {"site": "youtube" if name in ("yt", "youtube") else name}
            intent.confidence = 0.85
            return intent
        intent.kind = "deterministic"
        intent.action = "open_app"
        intent.args = {"name": name}
        intent.confidence = 0.8
        return intent

    intent.kind = "llm"
    intent.confidence = 0.5
    return intent
