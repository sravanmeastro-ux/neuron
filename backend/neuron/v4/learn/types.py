"""V4.9 typed procedure learning models.

Boundaries:
  ConversationState — short-lived linguistic context
  DesktopWorldModel — observable desktop
  TaskPlan — execution
  ProcedureRegistry — reusable workflow definitions (this layer + procedures.py)
  Preferences — small durable choices
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class ProcedureSource(str, Enum):
    BUILT_IN = "BUILT_IN"
    LEGACY = "LEGACY"
    USER_DEFINED = "USER_DEFINED"
    LEARNED = "LEARNED"
    CANDIDATE = "CANDIDATE"


class PreferenceScope(str, Enum):
    GLOBAL = "GLOBAL"
    DOMAIN = "DOMAIN"
    PROCEDURE = "PROCEDURE"
    TASK = "TASK"


@dataclass
class ProcedureParameter:
    name: str
    param_type: str = "string"  # string | int | monitor | app | url | ordinal
    description: str = ""
    default: Any = None
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "param_type": self.param_type,
            "description": self.description[:120],
            "default": self.default,
            "required": self.required,
        }


@dataclass
class ProcedureStep:
    capability_id: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    param_bindings: dict[str, str] = field(default_factory=dict)  # arg → param name
    expected_result: str = ""
    verification_kind: str = ""
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "tool": self.tool,
            "arguments": {k: str(v)[:80] for k, v in list(self.arguments.items())[:12]},
            "param_bindings": dict(self.param_bindings),
            "expected_result": self.expected_result[:120],
            "verification_kind": self.verification_kind,
            "optional": self.optional,
        }

    def to_legacy_step(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        args = dict(self.arguments)
        for arg_key, pname in self.param_bindings.items():
            if pname in params:
                args[arg_key] = params[pname]
        # Also replace {param} placeholders in string values
        for k, v in list(args.items()):
            if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                key = v[1:-1]
                if key in params:
                    args[k] = params[key]
        return {
            "action": self.tool or self.capability_id,
            "args": args,
            "expected_result": self.expected_result,
            "capability_id": self.capability_id,
        }


@dataclass
class ProcedureDefinition:
    procedure_id: str = ""
    name: str = ""
    description: str = ""
    intent_family: str = ""
    parameters: list[ProcedureParameter] = field(default_factory=list)
    steps: list[ProcedureStep] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    risk_summary: str = "safe"
    verification_requirements: list[str] = field(default_factory=list)
    source: ProcedureSource = ProcedureSource.LEARNED
    version: int = 1
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True
    confidence: float = 0.5
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    attempts: int = 0
    verified_successes: int = 0
    verified_failures: int = 0
    uncertain_outcomes: int = 0
    recovery_required: int = 0
    evidence_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.procedure_id:
            self.procedure_id = _id("proc")

    @property
    def success_rate(self) -> float:
        if self.attempts <= 0:
            return 0.0
        return self.verified_successes / max(1, self.attempts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "name": self.name,
            "description": self.description[:200],
            "intent_family": self.intent_family,
            "parameters": [p.to_dict() for p in self.parameters],
            "steps": [s.to_dict() for s in self.steps],
            "preconditions": list(self.preconditions),
            "completion_criteria": list(self.completion_criteria),
            "risk_summary": self.risk_summary,
            "source": self.source.value,
            "version": self.version,
            "aliases": list(self.aliases)[:12],
            "enabled": self.enabled,
            "confidence": round(self.confidence, 3),
            "evidence_count": self.evidence_count,
            "attempts": self.attempts,
            "verified_successes": self.verified_successes,
            "success_rate": round(self.success_rate, 3),
        }

    def fingerprint(self) -> str:
        """Structural fingerprint for deduplication (not display name)."""
        parts = [self.intent_family]
        for s in self.steps:
            tool = s.tool or s.capability_id
            binds = ",".join(sorted(s.param_bindings.values()))
            parts.append(f"{tool}:{binds}")
        return "|".join(parts)


@dataclass
class TraceStep:
    capability_id: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    verification: str = ""  # SUCCESS | FAILURE | UNCERTAIN
    recovery_used: bool = False
    expected_result: str = ""


@dataclass
class VerifiedTaskTrace:
    trace_id: str = ""
    goal_text: str = ""
    intent_family: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    final_status: str = ""  # SUCCESS | FAILURE | UNCERTAIN | CANCELLED
    task_verified: bool = False
    safety_ok: bool = True
    cancelled: bool = False
    blocked: bool = False
    at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trace_id:
            self.trace_id = _id("trace")

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "goal_text": self.goal_text[:160],
            "intent_family": self.intent_family,
            "n_steps": len(self.steps),
            "final_status": self.final_status,
            "task_verified": self.task_verified,
            "cancelled": self.cancelled,
            "blocked": self.blocked,
        }


@dataclass
class ProcedureCandidate:
    candidate_id: str = ""
    name: str = ""
    intent_family: str = ""
    parameters: list[ProcedureParameter] = field(default_factory=list)
    steps: list[ProcedureStep] = field(default_factory=list)
    confidence: float = 0.0
    evidence_count: int = 1
    risk_summary: str = "safe"
    completion_criteria: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    fingerprint: str = ""
    rejected: bool = False
    reject_reason: str = ""
    privacy_ok: bool = True

    def __post_init__(self) -> None:
        if not self.candidate_id:
            self.candidate_id = _id("cand")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "intent_family": self.intent_family,
            "confidence": round(self.confidence, 3),
            "evidence_count": self.evidence_count,
            "n_steps": len(self.steps),
            "n_params": len(self.parameters),
            "fingerprint": self.fingerprint,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason[:160],
            "privacy_ok": self.privacy_ok,
        }


@dataclass
class Preference:
    key: str
    value: str
    scope: PreferenceScope = PreferenceScope.GLOBAL
    domain: str = ""
    procedure_id: str = ""
    explicit: bool = True
    confidence: float = 1.0
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value[:120],
            "scope": self.scope.value,
            "domain": self.domain,
            "procedure_id": self.procedure_id,
            "explicit": self.explicit,
            "confidence": round(self.confidence, 3),
        }


# Central thresholds — do not scatter
MIN_STEPS_FOR_PROCEDURE = 2
MIN_EVIDENCE_FOR_AUTO_ACCEPT = 3
COORDINATE_KEYS = frozenset({"x", "y", "px", "py", "screen_x", "screen_y"})


__all__ = [
    "ProcedureSource",
    "PreferenceScope",
    "ProcedureParameter",
    "ProcedureStep",
    "ProcedureDefinition",
    "TraceStep",
    "VerifiedTaskTrace",
    "ProcedureCandidate",
    "Preference",
    "MIN_STEPS_FOR_PROCEDURE",
    "MIN_EVIDENCE_FOR_AUTO_ACCEPT",
    "COORDINATE_KEYS",
]
