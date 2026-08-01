"""V4.3 semantic resolution types."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from neuron.v4.world.models import UIElementState


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    STALE_WORLD = "STALE_WORLD"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class ConfidenceBand(str, Enum):
    HIGH = "HIGH"  # >= 0.75 — usable target
    MEDIUM = "MEDIUM"  # 0.45–0.74 — may need more observe/reason
    LOW = "LOW"  # < 0.45 — do not auto-act


class RevalidateStatus(str, Enum):
    STILL_VALID = "STILL_VALID"
    MOVED = "MOVED"
    CHANGED = "CHANGED"
    MISSING = "MISSING"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class ElementReference:
    """Parsed semantic intent from a natural reference."""

    raw: str = ""
    role_hint: str = ""  # normalized semantic role
    name_hint: str = ""  # textual / semantic name tokens
    ordinal: int | None = None  # 1-based; -1 = last
    ordinal_word: str = ""
    position: str = ""  # left|right|top|bottom|center|top_left|…
    relation: str = ""  # above|below|left_of|right_of|next_to|near
    relation_anchor: str = ""  # text of anchor for relational
    color: str = ""
    application: str = ""
    window: str = ""
    monitor_id: int | None = None
    deixis: str = ""  # it|this|that|this_one|that_one
    action_hint: str = ""  # click|play|focus|…
    visual_attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolutionContext:
    """Session / task context for resolution (from ContextEngine + world)."""

    task: str = ""
    active_application: str = ""
    active_window: str = ""
    active_monitor: int | None = None
    browser_url: str = ""
    browser_page_type: str = ""
    last_element_id: str = ""
    last_element_name: str = ""
    last_element_role: str = ""
    last_result_ids: list[str] = field(default_factory=list)
    last_action: str = ""
    focused_element_id: str = ""
    world_timestamp: float = 0.0
    max_world_age_s: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ElementCandidate:
    element: UIElementState
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    raw_role: str = ""
    normalized_role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element.id,
            "name": self.element.name,
            "role": self.normalized_role or self.element.role,
            "raw_role": self.raw_role,
            "score": round(self.score, 4),
            "reasons": list(self.reasons),
            "bounds": self.element.bounds,
            "source": self.element.source,
            "confidence": self.element.confidence,
        }


@dataclass
class ResolvedElement:
    element_id: str = ""
    role: str = ""
    raw_role: str = ""
    name: str = ""
    text: str = ""
    application: str = ""
    window: str = ""
    monitor_id: int | None = None
    bounds: dict[str, int] | None = None
    source: str = ""
    confidence: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ui(
        cls,
        el: UIElementState,
        *,
        confidence: float,
        raw_role: str = "",
        normalized_role: str = "",
    ) -> "ResolvedElement":
        return cls(
            element_id=el.id or "",
            role=normalized_role or el.role,
            raw_role=raw_role or str((el.attributes or {}).get("control_type") or el.role),
            name=el.name or "",
            text=el.text or el.name or "",
            application=el.application or "",
            window=el.window or "",
            monitor_id=el.monitor_id,
            bounds=dict(el.bounds) if el.bounds else None,
            source=el.source or "",
            confidence=float(confidence),
            attributes=dict(el.attributes or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolutionResult:
    status: ResolutionStatus = ResolutionStatus.NOT_FOUND
    reference: ElementReference = field(default_factory=ElementReference)
    resolved: ResolvedElement | None = None
    candidates: list[ElementCandidate] = field(default_factory=list)
    confidence: float = 0.0
    confidence_band: ConfidenceBand = ConfidenceBand.LOW
    evidence: str = ""
    clarification_prompt: str = ""
    latency_ms: float = 0.0
    needs_reobserve: bool = False
    timestamp: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED and self.resolved is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "confidence": round(self.confidence, 4),
            "confidence_band": self.confidence_band.value,
            "evidence": self.evidence,
            "clarification_prompt": self.clarification_prompt,
            "latency_ms": round(self.latency_ms, 2),
            "needs_reobserve": self.needs_reobserve,
            "reference": self.reference.to_dict(),
            "resolved": self.resolved.to_dict() if self.resolved else None,
            "candidates": [c.to_dict() for c in self.candidates[:12]],
            "candidate_count": len(self.candidates),
        }


def band_for(confidence: float) -> ConfidenceBand:
    if confidence >= 0.75:
        return ConfidenceBand.HIGH
    if confidence >= 0.45:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW
