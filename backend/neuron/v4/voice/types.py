"""V4.10 hierarchical voice routing types and metrics."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _rid() -> str:
    return f"vr_{uuid.uuid4().hex[:12]}"


class VoiceRoutingMode(str, Enum):
    LEGACY = "LEGACY"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    HIERARCHICAL = "HIERARCHICAL"


class RouteKind(str, Enum):
    LEGACY = "legacy"
    HIERARCHICAL_SHADOW = "hierarchical_shadow"
    HIERARCHICAL_CANARY = "hierarchical_canary"
    HIERARCHICAL = "hierarchical"
    FALLBACK_LEGACY = "fallback_legacy"


class TaskOutcomeKind(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNCERTAIN = "UNCERTAIN"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


# Process-wide counters (tests reset via reset_voice_metrics)
VOICE_SHADOW_MISMATCH_COUNT = 0
SHADOW_MUTATION_COUNT = 0
VOICE_SAFETY_MISMATCH_COUNT = 0
VOICE_DUPLICATE_EXECUTION_COUNT = 0
UNVERIFIED_COMPLETION_RESPONSE_COUNT = 0


def reset_voice_metrics() -> None:
    global VOICE_SHADOW_MISMATCH_COUNT, SHADOW_MUTATION_COUNT
    global VOICE_SAFETY_MISMATCH_COUNT, VOICE_DUPLICATE_EXECUTION_COUNT
    global UNVERIFIED_COMPLETION_RESPONSE_COUNT
    VOICE_SHADOW_MISMATCH_COUNT = 0
    SHADOW_MUTATION_COUNT = 0
    VOICE_SAFETY_MISMATCH_COUNT = 0
    VOICE_DUPLICATE_EXECUTION_COUNT = 0
    UNVERIFIED_COMPLETION_RESPONSE_COUNT = 0


def note_shadow_mismatch() -> None:
    global VOICE_SHADOW_MISMATCH_COUNT
    VOICE_SHADOW_MISMATCH_COUNT += 1


def note_shadow_mutation() -> None:
    global SHADOW_MUTATION_COUNT
    SHADOW_MUTATION_COUNT += 1


def note_safety_mismatch() -> None:
    global VOICE_SAFETY_MISMATCH_COUNT
    VOICE_SAFETY_MISMATCH_COUNT += 1


def note_duplicate_execution() -> None:
    global VOICE_DUPLICATE_EXECUTION_COUNT
    VOICE_DUPLICATE_EXECUTION_COUNT += 1


def note_unverified_completion() -> None:
    global UNVERIFIED_COMPLETION_RESPONSE_COUNT
    UNVERIFIED_COMPLETION_RESPONSE_COUNT += 1


@dataclass
class VoiceRequest:
    """Normalized voice request — shared by legacy and hierarchical."""

    text: str
    normalized: str = ""
    request_id: str = field(default_factory=_rid)
    stt_confidence: float | None = None
    intent_family: str = ""
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.normalized:
            self.normalized = self.text


@dataclass
class RouteDecision:
    route: RouteKind
    eligible: bool
    reason: str
    intent_family: str = ""
    capability_ids: list[str] = field(default_factory=list)
    risk: str = "safe"
    committed: bool = False
    request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "eligible": self.eligible,
            "reason": self.reason[:160],
            "intent_family": self.intent_family,
            "capability_ids": list(self.capability_ids)[:8],
            "risk": self.risk,
            "committed": self.committed,
            "request_id": self.request_id,
        }


@dataclass
class LatencySample:
    understand_ms: float = 0.0
    plan_ms: float = 0.0
    first_action_ms: float = 0.0
    verify_ms: float = 0.0
    recovery_ms: float = 0.0
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "understand_ms": round(self.understand_ms, 2),
            "plan_ms": round(self.plan_ms, 2),
            "first_action_ms": round(self.first_action_ms, 2),
            "verify_ms": round(self.verify_ms, 2),
            "recovery_ms": round(self.recovery_ms, 2),
            "total_ms": round(self.total_ms, 2),
        }


@dataclass
class ShadowComparison:
    request_id: str
    legacy_intent: str = ""
    hierarchical_intent: str = ""
    legacy_tools: list[str] = field(default_factory=list)
    hierarchical_tools: list[str] = field(default_factory=list)
    semantic_match: bool = True
    mismatch_reason: str = ""
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "legacy_intent": self.legacy_intent,
            "hierarchical_intent": self.hierarchical_intent,
            "legacy_tools": list(self.legacy_tools)[:8],
            "hierarchical_tools": list(self.hierarchical_tools)[:8],
            "semantic_match": self.semantic_match,
            "mismatch_reason": self.mismatch_reason[:160],
            "mutated": self.mutated,
        }


@dataclass
class MigrationReadinessReport:
    mock_parity_pass: bool = False
    shadow_parity_pass: bool = False
    live_parity_pass: str = "NOT_RUN"  # True | False | NOT_RUN
    safety_pass: bool = False
    false_success_pass: bool = False
    recovery_loop_pass: bool = False
    context_pass: bool = False
    latency_pass: bool = False
    canary_sample_count: int = 0
    live_sample_count: int = 0
    soak_status: str = "NOT_RUN"
    procedure_learning_off: bool = True
    default_still_legacy: bool = True
    blockers: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def ready_for_default(self) -> bool:
        """Computed only — never manually forced True.

        Requires LIVE+soak gates. Being temporarily in CANARY for validation
        does not block readiness; already being on HIERARCHICAL does (via blockers).
        """
        if self.blockers:
            return False
        if self.live_parity_pass != True and self.live_parity_pass != "PASS":
            return False
        if self.soak_status not in (True, "PASS"):
            return False
        return bool(
            self.mock_parity_pass
            and self.shadow_parity_pass
            and self.safety_pass
            and self.false_success_pass
            and self.recovery_loop_pass
            and self.context_pass
            and self.latency_pass
            and self.canary_sample_count >= 20
            and self.live_sample_count >= 20
            and self.procedure_learning_off
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mock_parity_pass": self.mock_parity_pass,
            "shadow_parity_pass": self.shadow_parity_pass,
            "live_parity_pass": self.live_parity_pass,
            "safety_pass": self.safety_pass,
            "false_success_pass": self.false_success_pass,
            "recovery_loop_pass": self.recovery_loop_pass,
            "context_pass": self.context_pass,
            "latency_pass": self.latency_pass,
            "canary_sample_count": self.canary_sample_count,
            "live_sample_count": self.live_sample_count,
            "soak_status": self.soak_status,
            "procedure_learning_off": self.procedure_learning_off,
            "default_still_legacy": self.default_still_legacy,
            "ready_for_default": self.ready_for_default,
            "blockers": list(self.blockers),
            "metrics": dict(self.metrics),
        }


def voice_metrics() -> dict[str, int]:
    return {
        "VOICE_SHADOW_MISMATCH_COUNT": VOICE_SHADOW_MISMATCH_COUNT,
        "SHADOW_MUTATION_COUNT": SHADOW_MUTATION_COUNT,
        "VOICE_SAFETY_MISMATCH_COUNT": VOICE_SAFETY_MISMATCH_COUNT,
        "VOICE_DUPLICATE_EXECUTION_COUNT": VOICE_DUPLICATE_EXECUTION_COUNT,
        "UNVERIFIED_COMPLETION_RESPONSE_COUNT": UNVERIFIED_COMPLETION_RESPONSE_COUNT,
    }


__all__ = [
    "VoiceRoutingMode",
    "RouteKind",
    "TaskOutcomeKind",
    "VoiceRequest",
    "RouteDecision",
    "LatencySample",
    "ShadowComparison",
    "MigrationReadinessReport",
    "voice_metrics",
    "reset_voice_metrics",
    "note_shadow_mismatch",
    "note_shadow_mutation",
    "note_safety_mismatch",
    "note_duplicate_execution",
    "note_unverified_completion",
    "VOICE_SHADOW_MISMATCH_COUNT",
    "SHADOW_MUTATION_COUNT",
    "VOICE_SAFETY_MISMATCH_COUNT",
    "VOICE_DUPLICATE_EXECUTION_COUNT",
    "UNVERIFIED_COMPLETION_RESPONSE_COUNT",
]
