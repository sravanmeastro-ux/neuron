"""V4.5 verification types — expectations, evidence, authoritative outcome.

ActionResult (tool executed) ≠ VerificationOutcome (world evidence).
UNCERTAIN never becomes SUCCESS automatically.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from neuron.v4.types import VerificationOutcome


class ExpectationKind(str, Enum):
    PROCESS_EXISTS = "PROCESS_EXISTS"
    WINDOW_EXISTS = "WINDOW_EXISTS"
    WINDOW_VISIBLE = "WINDOW_VISIBLE"
    WINDOW_FOCUSED = "WINDOW_FOCUSED"
    WINDOW_ON_MONITOR = "WINDOW_ON_MONITOR"
    WINDOW_MAXIMIZED = "WINDOW_MAXIMIZED"
    WINDOW_FULLSCREEN = "WINDOW_FULLSCREEN"
    MEDIA_FULLSCREEN = "MEDIA_FULLSCREEN"
    ELEMENT_EXISTS = "ELEMENT_EXISTS"
    ELEMENT_DISAPPEARED = "ELEMENT_DISAPPEARED"
    ELEMENT_STATE_CHANGED = "ELEMENT_STATE_CHANGED"
    FOCUSED_ELEMENT = "FOCUSED_ELEMENT"
    TEXT_PRESENT = "TEXT_PRESENT"
    TEXT_IN_FIELD = "TEXT_IN_FIELD"
    URL_MATCH = "URL_MATCH"
    PAGE_STATE = "PAGE_STATE"
    MEDIA_STATE = "MEDIA_STATE"
    SCREEN_CHANGED = "SCREEN_CHANGED"
    APP_OPEN = "APP_OPEN"
    CUSTOM = "CUSTOM"
    NONE = "NONE"


class VerificationMethod(str, Enum):
    WORLD_DIFF = "WORLD_DIFF"
    WINDOW_QUERY = "WINDOW_QUERY"
    MONITOR_GEOMETRY = "MONITOR_GEOMETRY"
    BROWSER_STATE = "BROWSER_STATE"
    ELEMENT_REVALIDATE = "ELEMENT_REVALIDATE"
    SCREEN_DIFF = "SCREEN_DIFF"
    DOMAIN_VERIFIER = "DOMAIN_VERIFIER"
    LEGACY_BRIDGE = "LEGACY_BRIDGE"
    COMPOSITE = "COMPOSITE"
    WAIT_POLL = "WAIT_POLL"


# Confidence bands (central thresholds — do not scatter magic numbers)
CONF_HIGH = 0.85
CONF_MEDIUM = 0.55
CONF_LOW = 0.35
CONF_SUCCESS_MIN = 0.55  # below this → cannot be SUCCESS


@dataclass
class VerificationExpectation:
    kind: ExpectationKind = ExpectationKind.NONE
    application: str = ""
    monitor: Any = None
    element_id: str = ""
    url_substr: str = ""
    text: str = ""
    media_want: str = ""  # playing | paused | fullscreen
    sensitive: bool = False
    timeout_s: float = 3.0
    poll_s: float = 0.15
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class VerificationEvidence:
    """Bounded structured evidence — no screenshots / secrets."""

    facts: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    before_fp: str = ""
    after_fp: str = ""

    def add(self, key: str, value: Any, *, source: str = "") -> None:
        if key in ("password", "token", "secret", "credential"):
            return
        # Bound string values
        if isinstance(value, str) and len(value) > 160:
            value = value[:157] + "..."
        self.facts[key] = value
        if source and source not in self.sources:
            self.sources.append(source)

    def summary(self, *, limit: int = 8) -> str:
        parts = []
        for i, (k, v) in enumerate(self.facts.items()):
            if i >= limit:
                break
            parts.append(f"{k}={v}")
        if self.conflicts:
            parts.append(f"conflicts={len(self.conflicts)}")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": dict(self.facts),
            "sources": list(self.sources)[:12],
            "conflicts": list(self.conflicts)[:8],
            "before_fp": self.before_fp[:32],
            "after_fp": self.after_fp[:32],
            "summary": self.summary(),
        }


@dataclass
class VerificationReport:
    """Authoritative verification decision for V4."""

    status: VerificationOutcome = VerificationOutcome.UNCERTAIN
    action_id: str = ""
    task_id: str = ""
    expected_result: str = ""
    expectation: VerificationExpectation | None = None
    evidence: VerificationEvidence = field(default_factory=VerificationEvidence)
    confidence: float = 0.0
    reason: str = ""
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    verification_method: str = VerificationMethod.COMPOSITE.value
    latency_ms: float = 0.0
    retryable: bool = True
    cancelled: bool = False
    action_result_ok: bool | None = None  # separate from status
    legacy_ok: bool | None = None
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.action_id:
            self.action_id = f"act_{uuid.uuid4().hex[:10]}"

    @property
    def outcome(self) -> VerificationOutcome:
        return self.status

    @property
    def success(self) -> bool:
        return self.status is VerificationOutcome.SUCCESS

    @property
    def ok_for_advance(self) -> bool:
        """Only SUCCESS advances plans. UNCERTAIN/FAILURE do not."""
        return self.status is VerificationOutcome.SUCCESS

    def to_v4_result(self):
        from neuron.v4.types import VerificationResult

        return VerificationResult(
            outcome=self.status,
            detail=self.reason,
            evidence=self.evidence.to_dict(),
            category="" if self.status is not VerificationOutcome.FAILURE else "VERIFY_FAILED",
        )

    def to_legacy_ok(self) -> bool:
        """
        Bridge to binary VerifyResult.ok for OPAVR GoalState.
        SUCCESS → True; FAILURE → False; UNCERTAIN → False
        (never treat UNCERTAIN as success).
        """
        return self.status is VerificationOutcome.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action_id": self.action_id,
            "task_id": self.task_id,
            "expected_result": self.expected_result[:160],
            "expectation": self.expectation.to_dict() if self.expectation else None,
            "evidence": self.evidence.to_dict(),
            "confidence": round(self.confidence, 4),
            "reason": self.reason[:240],
            "before_snapshot_id": self.before_snapshot_id[:32],
            "after_snapshot_id": self.after_snapshot_id[:32],
            "verification_method": self.verification_method,
            "latency_ms": round(self.latency_ms, 2),
            "retryable": self.retryable,
            "cancelled": self.cancelled,
            "action_result_ok": self.action_result_ok,
            "legacy_ok": self.legacy_ok,
        }


# Default timeouts by expectation family
TIMEOUTS: dict[str, float] = {
    "focus": 1.5,
    "move": 2.0,
    "open_app": 8.0,
    "browser": 10.0,
    "click": 2.5,
    "type": 2.0,
    "fullscreen": 3.0,
    "media": 5.0,
    "default": 3.0,
}


def timeout_for(kind: ExpectationKind | str, tool: str = "") -> float:
    t = (tool or "").lower()
    k = kind.value if isinstance(kind, ExpectationKind) else str(kind)
    if "open" in t or k in ("APP_OPEN", "WINDOW_EXISTS", "PROCESS_EXISTS"):
        return TIMEOUTS["open_app"]
    if "focus" in t or k == "WINDOW_FOCUSED":
        return TIMEOUTS["focus"]
    if "monitor" in t or "move" in t or k == "WINDOW_ON_MONITOR":
        return TIMEOUTS["move"]
    if "browser" in t or "youtube" in t or "url" in t.lower() or k in ("URL_MATCH", "PAGE_STATE"):
        return TIMEOUTS["browser"]
    if "fullscreen" in t or k in ("WINDOW_FULLSCREEN", "MEDIA_FULLSCREEN"):
        return TIMEOUTS["fullscreen"]
    if "click" in t or "type" in t:
        return TIMEOUTS["click"]
    return TIMEOUTS["default"]


__all__ = [
    "ExpectationKind",
    "VerificationMethod",
    "VerificationExpectation",
    "VerificationEvidence",
    "VerificationReport",
    "CONF_HIGH",
    "CONF_MEDIUM",
    "CONF_LOW",
    "CONF_SUCCESS_MIN",
    "TIMEOUTS",
    "timeout_for",
    "VerificationOutcome",
]
