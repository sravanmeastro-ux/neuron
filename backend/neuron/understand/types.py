"""Semantic understanding types — Intent Understanding Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntitySpan:
    kind: str  # application | website | query | monitor | ordinal | path
    value: str
    raw: str = ""
    confidence: float = 0.0


@dataclass
class SemanticUnderstanding:
    raw: str
    cleaned: str = ""
    # Canonical command FastIntentRouter can execute (e.g. "open chrome")
    rewritten: str = ""
    intent_id: str = "UNKNOWN"
    intent_label: str = ""
    confidence: float = 0.0
    band: str = "low"  # high | medium | low
    entities: list[EntitySpan] = field(default_factory=list)
    context_used: list[str] = field(default_factory=list)
    clarify_prompt: str | None = None
    embedding_scores: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    source: str = "semantic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "cleaned": self.cleaned,
            "rewritten": self.rewritten,
            "intent_id": self.intent_id,
            "intent_label": self.intent_label,
            "confidence": round(self.confidence, 3),
            "band": self.band,
            "entities": [
                {"kind": e.kind, "value": e.value, "raw": e.raw, "confidence": e.confidence}
                for e in self.entities
            ],
            "context_used": list(self.context_used),
            "clarify_prompt": self.clarify_prompt,
            "latency_ms": round(self.latency_ms, 2),
            "source": self.source,
        }
