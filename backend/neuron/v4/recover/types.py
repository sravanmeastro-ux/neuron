"""V4.6 recovery types — diagnosis, decisions, budgets, history.

RecoveryDecision here is the authoritative V4 shape.
neuron.v4.types.RecoveryDecision remains a thin compatibility façade.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from neuron.v4.types import VerificationOutcome


class FailureCategory(str, Enum):
    PERCEPTION_FAILURE = "PERCEPTION_FAILURE"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_STALE = "TARGET_STALE"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    FOCUS_FAILURE = "FOCUS_FAILURE"
    WINDOW_FAILURE = "WINDOW_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    ACTION_NO_EFFECT = "ACTION_NO_EFFECT"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    VERIFICATION_UNCERTAIN = "VERIFICATION_UNCERTAIN"
    TIMEOUT = "TIMEOUT"
    APPLICATION_NOT_READY = "APPLICATION_NOT_READY"
    APPLICATION_CLOSED = "APPLICATION_CLOSED"
    DEPENDENCY_UNMET = "DEPENDENCY_UNMET"
    INVALID_TOOL = "INVALID_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SAFETY_DENIED = "SAFETY_DENIED"
    USER_CANCELLED = "USER_CANCELLED"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"
    # V3 aliases retained for bridge
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    APP_NOT_RUNNING = "APP_NOT_RUNNING"
    PAGE_NOT_LOADED = "PAGE_NOT_LOADED"
    POPUP_DETECTED = "POPUP_DETECTED"
    WRONG_MONITOR = "WRONG_MONITOR"


class RecoveryKind(str, Enum):
    REOBSERVE = "REOBSERVE"
    REGROUND = "REGROUND"
    RETRY = "RETRY"
    ALTERNATE_TOOL = "ALTERNATE_TOOL"
    REPLAN = "REPLAN"
    CLARIFY = "CLARIFY"
    WAIT = "WAIT"
    FAIL = "FAIL"
    CANCEL = "CANCEL"
    FOCUS_THEN_RETRY = "FOCUS_THEN_RETRY"
    NONE = "NONE"


class RecoveryStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    WAITING = "WAITING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    BLOCKED = "BLOCKED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


# Central budgets — do not scatter magic numbers
class RecoveryBudget:
    MAX_SAME_ACTION_RETRIES = 1
    MAX_REOBSERVE = 2
    MAX_REGROUND = 2
    MAX_ALTERNATE = 2
    MAX_REPLAN = 2
    MAX_TOTAL_RECOVERY = 6
    MAX_WAIT_S = 5.0
    CYCLE_THRESHOLD = 2  # same fingerprint+tool+category

    def __init__(
        self,
        *,
        same_action: int | None = None,
        reobserve: int | None = None,
        reground: int | None = None,
        alternate: int | None = None,
        replan: int | None = None,
        total: int | None = None,
    ):
        self.same_action_limit = same_action if same_action is not None else self.MAX_SAME_ACTION_RETRIES
        self.reobserve_limit = reobserve if reobserve is not None else self.MAX_REOBSERVE
        self.reground_limit = reground if reground is not None else self.MAX_REGROUND
        self.alternate_limit = alternate if alternate is not None else self.MAX_ALTERNATE
        self.replan_limit = replan if replan is not None else self.MAX_REPLAN
        self.total_limit = total if total is not None else self.MAX_TOTAL_RECOVERY
        self.same_action_used = 0
        self.reobserve_used = 0
        self.reground_used = 0
        self.alternate_used = 0
        self.replan_used = 0
        self.total_used = 0

    def remaining(self, kind: str) -> int:
        k = (kind or "").upper()
        if k in ("RETRY", "SAME"):
            return max(0, self.same_action_limit - self.same_action_used)
        if k == "REOBSERVE":
            return max(0, self.reobserve_limit - self.reobserve_used)
        if k == "REGROUND":
            return max(0, self.reground_limit - self.reground_used)
        if k in ("ALTERNATE_TOOL", "ALTERNATE"):
            return max(0, self.alternate_limit - self.alternate_used)
        if k == "REPLAN":
            return max(0, self.replan_limit - self.replan_used)
        return max(0, self.total_limit - self.total_used)

    def can(self, kind: str) -> bool:
        return self.remaining("TOTAL") > 0 and self.remaining(kind) > 0

    def consume(self, kind: str) -> None:
        k = (kind or "").upper()
        self.total_used += 1
        if k in ("RETRY", "SAME", "FOCUS_THEN_RETRY"):
            self.same_action_used += 1
        elif k == "REOBSERVE":
            self.reobserve_used += 1
        elif k == "REGROUND":
            self.reground_used += 1
        elif k in ("ALTERNATE_TOOL", "ALTERNATE"):
            self.alternate_used += 1
        elif k == "REPLAN":
            self.replan_used += 1

    def exhausted(self) -> bool:
        return self.total_used >= self.total_limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "same_action": f"{self.same_action_used}/{self.same_action_limit}",
            "reobserve": f"{self.reobserve_used}/{self.reobserve_limit}",
            "reground": f"{self.reground_used}/{self.reground_limit}",
            "alternate": f"{self.alternate_used}/{self.alternate_limit}",
            "replan": f"{self.replan_used}/{self.replan_limit}",
            "total": f"{self.total_used}/{self.total_limit}",
        }


@dataclass
class FailureDiagnosis:
    task_id: str = ""
    action_id: str = ""
    subgoal_id: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN_FAILURE
    reason: str = ""
    verification_status: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    world_before_fp: str = ""
    world_after_fp: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    retryable: bool = True
    confidence: float = 0.5
    v3_category: str = ""  # bridge
    ask_prompt: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        return d

    def to_v3_dict(self) -> dict[str, Any]:
        cat = self.v3_category or _to_v3_category(self.category)
        return {
            "category": cat,
            "cause": cat.lower(),
            "detail": self.reason,
            "action": self.tool,
            "target": str((self.args or {}).get("name") or (self.args or {}).get("text") or ""),
            "expected_result": "",
            "world": {},
            "strategy": "alternate",
            "ask_prompt": self.ask_prompt,
        }


@dataclass
class RecoveryAction:
    """Concrete next step suggested by recovery (not yet executed)."""

    kind: RecoveryKind = RecoveryKind.NONE
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    reference: str = ""  # for reground
    observe_targets: list[str] = field(default_factory=list)  # windows|focus|browser|elements
    expected_result: str = ""
    requires_verify: bool = True
    reason: str = ""

    def to_legacy_step(self) -> dict[str, Any]:
        if self.kind in (RecoveryKind.REOBSERVE, RecoveryKind.WAIT, RecoveryKind.CLARIFY,
                         RecoveryKind.FAIL, RecoveryKind.CANCEL, RecoveryKind.REPLAN, RecoveryKind.NONE):
            if self.kind is RecoveryKind.WAIT:
                return {"action": "wait", "args": dict(self.arguments) or {"seconds": 1.0}}
            return {}
        return {
            "action": self.tool,
            "args": dict(self.arguments),
            "expected_result": self.expected_result,
            "target": self.reference or self.tool,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "reference": self.reference,
            "observe_targets": list(self.observe_targets),
            "expected_result": self.expected_result,
            "requires_verify": self.requires_verify,
            "reason": self.reason,
        }


@dataclass
class RecoveryDecision:
    """Authoritative V4 recovery decision."""

    kind: RecoveryKind = RecoveryKind.NONE
    diagnosis: FailureDiagnosis | None = None
    actions: list[RecoveryAction] = field(default_factory=list)
    reason: str = ""
    clarify_prompt: str = ""
    retry_count: int = 0
    remaining_budget: dict[str, Any] = field(default_factory=dict)
    safety_tier: str = "safe"
    confidence: float = 0.5
    status: RecoveryStatus = RecoveryStatus.READY
    decision_id: str = ""
    latency_ms: float = 0.0
    # Compatibility with v3 decide_recovery
    strategy: str = ""  # retry|alternate|replan|ask_user|blocked|fail
    v3_status: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id:
            self.decision_id = f"rec_{uuid.uuid4().hex[:10]}"
        if not self.strategy:
            self.strategy = _kind_to_v3_strategy(self.kind)

    @property
    def primary_action(self) -> RecoveryAction | None:
        return self.actions[0] if self.actions else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "kind": self.kind.value,
            "strategy": self.strategy,
            "v3_status": self.v3_status,
            "reason": self.reason[:240],
            "clarify_prompt": self.clarify_prompt[:200],
            "retry_count": self.retry_count,
            "remaining_budget": dict(self.remaining_budget),
            "safety_tier": self.safety_tier,
            "confidence": round(self.confidence, 4),
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis else None,
            "actions": [a.to_dict() for a in self.actions],
        }

    def to_v3(self):
        from neuron.v3.loop_types import RecoveryDecision as V3Dec
        status = self.v3_status or {
            RecoveryKind.CLARIFY: "NEEDS_USER",
            RecoveryKind.FAIL: "FAILED",
            RecoveryKind.CANCEL: "INTERRUPTED",
            RecoveryKind.REPLAN: "NEEDS_REPLAN",
        }.get(self.kind, "RETRY")
        if self.status is RecoveryStatus.BLOCKED:
            status = "BLOCKED"
        return V3Dec(
            strategy=self.strategy or _kind_to_v3_strategy(self.kind),
            status=status,
            category=(self.diagnosis.v3_category if self.diagnosis else "")
            or (self.diagnosis.category.value if self.diagnosis else "UNKNOWN"),
            ask_prompt=self.clarify_prompt,
            reason=self.reason,
        )


@dataclass
class RecoveryHistoryEntry:
    category: str = ""
    kind: str = ""
    tool: str = ""
    world_fp: str = ""
    verification: str = ""
    result: str = ""
    attempt: int = 0
    timestamp: float = field(default_factory=time.time)

    def fingerprint(self) -> str:
        # Kind excluded — same failure state across different recovery attempts = cycle
        return f"{self.category}|{self.tool}|{self.world_fp}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryHistory:
    entries: list[RecoveryHistoryEntry] = field(default_factory=list)
    max_entries: int = 24

    def add(self, entry: RecoveryHistoryEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def cycle_count(self, fingerprint: str) -> int:
        return sum(1 for e in self.entries if e.fingerprint() == fingerprint)

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]


def _to_v3_category(cat: FailureCategory) -> str:
    mapping = {
        FailureCategory.TARGET_NOT_FOUND: "ELEMENT_NOT_FOUND",
        FailureCategory.TARGET_STALE: "ELEMENT_NOT_FOUND",
        FailureCategory.TARGET_AMBIGUOUS: "AMBIGUOUS_TARGET",
        FailureCategory.FOCUS_FAILURE: "FOCUS_LOST",
        FailureCategory.WINDOW_FAILURE: "WINDOW_NOT_FOUND",
        FailureCategory.APPLICATION_NOT_READY: "APP_NOT_RUNNING",
        FailureCategory.APPLICATION_CLOSED: "APP_NOT_RUNNING",
        FailureCategory.TIMEOUT: "ACTION_TIMEOUT",
        FailureCategory.PERMISSION_DENIED: "PERMISSION_REQUIRED",
        FailureCategory.SAFETY_DENIED: "POLICY_BLOCKED",
        FailureCategory.USER_CANCELLED: "INTERRUPTED",
        FailureCategory.VERIFICATION_FAILURE: "VERIFICATION_FAILED",
        FailureCategory.VERIFICATION_UNCERTAIN: "VERIFICATION_FAILED",
        FailureCategory.ACTION_NO_EFFECT: "VERIFICATION_FAILED",
        FailureCategory.ELEMENT_NOT_FOUND: "ELEMENT_NOT_FOUND",
        FailureCategory.WINDOW_NOT_FOUND: "WINDOW_NOT_FOUND",
        FailureCategory.APP_NOT_RUNNING: "APP_NOT_RUNNING",
        FailureCategory.PAGE_NOT_LOADED: "PAGE_NOT_LOADED",
        FailureCategory.POPUP_DETECTED: "POPUP_DETECTED",
        FailureCategory.WRONG_MONITOR: "WRONG_MONITOR",
    }
    return mapping.get(cat, cat.value if cat.value in (
        "ELEMENT_NOT_FOUND", "WINDOW_NOT_FOUND", "APP_NOT_RUNNING", "PAGE_NOT_LOADED",
        "POPUP_DETECTED", "FOCUS_LOST", "WRONG_WINDOW", "WRONG_MONITOR", "ACTION_TIMEOUT",
        "VERIFICATION_FAILED", "PERMISSION_REQUIRED", "AMBIGUOUS_TARGET", "POLICY_BLOCKED",
        "INTERRUPTED", "UNKNOWN",
    ) else "UNKNOWN")


def _kind_to_v3_strategy(kind: RecoveryKind) -> str:
    return {
        RecoveryKind.RETRY: "retry",
        RecoveryKind.FOCUS_THEN_RETRY: "alternate",
        RecoveryKind.ALTERNATE_TOOL: "alternate",
        RecoveryKind.REOBSERVE: "retry",
        RecoveryKind.REGROUND: "alternate",
        RecoveryKind.WAIT: "retry",
        RecoveryKind.REPLAN: "replan",
        RecoveryKind.CLARIFY: "ask_user",
        RecoveryKind.FAIL: "fail",
        RecoveryKind.CANCEL: "fail",
    }.get(kind, "fail")


__all__ = [
    "FailureCategory",
    "RecoveryKind",
    "RecoveryStatus",
    "RecoveryBudget",
    "FailureDiagnosis",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryHistory",
    "RecoveryHistoryEntry",
    "VerificationOutcome",
]
