"""V3.7 adaptive AgentLoop types — failure categories + loop statuses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Failure categories (structured)
# ---------------------------------------------------------------------------

ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
APP_NOT_RUNNING = "APP_NOT_RUNNING"
PAGE_NOT_LOADED = "PAGE_NOT_LOADED"
POPUP_DETECTED = "POPUP_DETECTED"
FOCUS_LOST = "FOCUS_LOST"
WRONG_WINDOW = "WRONG_WINDOW"
WRONG_MONITOR = "WRONG_MONITOR"
ACTION_TIMEOUT = "ACTION_TIMEOUT"
VERIFICATION_FAILED = "VERIFICATION_FAILED"
PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
POLICY_BLOCKED = "POLICY_BLOCKED"
INTERRUPTED = "INTERRUPTED"
UNKNOWN = "UNKNOWN"

FAILURE_CATEGORIES = (
    ELEMENT_NOT_FOUND,
    WINDOW_NOT_FOUND,
    APP_NOT_RUNNING,
    PAGE_NOT_LOADED,
    POPUP_DETECTED,
    FOCUS_LOST,
    WRONG_WINDOW,
    WRONG_MONITOR,
    ACTION_TIMEOUT,
    VERIFICATION_FAILED,
    PERMISSION_REQUIRED,
    AMBIGUOUS_TARGET,
    POLICY_BLOCKED,
    INTERRUPTED,
    UNKNOWN,
)

# ---------------------------------------------------------------------------
# Loop / goal statuses
# ---------------------------------------------------------------------------

SUCCESS = "SUCCESS"
PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
RETRY = "RETRY"
NEEDS_REPLAN = "NEEDS_REPLAN"
NEEDS_USER = "NEEDS_USER"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
INTERRUPTED_STATUS = "INTERRUPTED"
RUNNING = "RUNNING"

# Recovery strategies
STRATEGY_RETRY = "retry"
STRATEGY_ALTERNATE = "alternate"
STRATEGY_REPLAN = "replan"
STRATEGY_ASK_USER = "ask_user"
STRATEGY_BLOCKED = "blocked"
STRATEGY_FAIL = "fail"


@dataclass
class Diagnosis:
    category: str = UNKNOWN
    cause: str = ""  # legacy short cause
    detail: str = ""
    action: str = ""
    target: str = ""
    expected_result: str = ""
    world: dict[str, Any] = field(default_factory=dict)
    strategy: str = STRATEGY_ALTERNATE
    ask_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryDecision:
    strategy: str
    status: str  # RETRY | NEEDS_REPLAN | NEEDS_USER | BLOCKED | FAILED
    category: str = UNKNOWN
    ask_prompt: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_recovery(
    diagnosis: Diagnosis | dict[str, Any],
    *,
    step_retries: int = 0,
    max_step_retries: int = 2,
    global_retries: int = 0,
    max_global_retries: int = 3,
    has_alternate: bool = False,
) -> RecoveryDecision:
    """
    Choose retry / alternate / replan / ask_user / fail from a diagnosis.

    Bounded: never suggests infinite retry.
    """
    if isinstance(diagnosis, dict):
        cat = str(diagnosis.get("category") or diagnosis.get("cause") or UNKNOWN)
        detail = str(diagnosis.get("detail") or "")
        ask = str(diagnosis.get("ask_prompt") or "")
    else:
        cat = diagnosis.category or diagnosis.cause or UNKNOWN
        detail = diagnosis.detail or ""
        ask = diagnosis.ask_prompt or ""

    cat_u = cat.upper() if isinstance(cat, str) else UNKNOWN
    # Map legacy causes → structured categories
    legacy_map = {
        "timeout": ACTION_TIMEOUT,
        "app_not_present": APP_NOT_RUNNING,
        "target_not_found": ELEMENT_NOT_FOUND,
        "window_missing": WINDOW_NOT_FOUND,
        "needs_confirm": PERMISSION_REQUIRED,
        "policy_blocked": POLICY_BLOCKED,
        "browser_state_mismatch": PAGE_NOT_LOADED,
        "monitor_mismatch": WRONG_MONITOR,
        "no_foreground_context": FOCUS_LOST,
        "focus": FOCUS_LOST,
        "wrong_window": WRONG_WINDOW,
        "popup": POPUP_DETECTED,
        "verification_failed": VERIFICATION_FAILED,
        "ambiguous": AMBIGUOUS_TARGET,
        "interrupted": INTERRUPTED,
        "unknown": UNKNOWN,
    }
    if cat_u not in FAILURE_CATEGORIES:
        cat_u = legacy_map.get(cat.lower(), cat_u if cat_u in FAILURE_CATEGORIES else UNKNOWN)

    if cat_u == POLICY_BLOCKED:
        return RecoveryDecision(
            STRATEGY_BLOCKED, BLOCKED, cat_u, reason=detail or "blocked by safety"
        )
    if cat_u == PERMISSION_REQUIRED:
        return RecoveryDecision(
            STRATEGY_ASK_USER,
            NEEDS_USER,
            cat_u,
            ask_prompt=ask or "I need your confirmation to continue.",
            reason=detail,
        )
    if cat_u == AMBIGUOUS_TARGET:
        return RecoveryDecision(
            STRATEGY_ASK_USER,
            NEEDS_USER,
            cat_u,
            ask_prompt=ask or "Which one did you mean?",
            reason=detail,
        )
    if cat_u == INTERRUPTED:
        return RecoveryDecision(
            STRATEGY_FAIL, INTERRUPTED_STATUS, cat_u, reason="Interrupted by user"
        )

    # Budget exhausted → fail (caller may still try one replan)
    if step_retries >= max_step_retries and global_retries >= max_global_retries:
        return RecoveryDecision(
            STRATEGY_FAIL, FAILED, cat_u, reason="retry budget exhausted"
        )

    # Prefer alternate method when available for structural misses
    if has_alternate and cat_u in (
        ELEMENT_NOT_FOUND,
        WINDOW_NOT_FOUND,
        APP_NOT_RUNNING,
        FOCUS_LOST,
        WRONG_WINDOW,
        WRONG_MONITOR,
        POPUP_DETECTED,
        VERIFICATION_FAILED,
        PAGE_NOT_LOADED,
        ACTION_TIMEOUT,
        UNKNOWN,
    ):
        return RecoveryDecision(
            STRATEGY_ALTERNATE, RETRY, cat_u, reason=f"alternate for {cat_u}"
        )

    # Same-step retry for transient issues
    if step_retries < max_step_retries and cat_u in (
        ACTION_TIMEOUT,
        PAGE_NOT_LOADED,
        FOCUS_LOST,
        POPUP_DETECTED,
        VERIFICATION_FAILED,
        WRONG_MONITOR,
    ):
        return RecoveryDecision(
            STRATEGY_RETRY, RETRY, cat_u, reason=f"retry {cat_u}"
        )

    if global_retries < max_global_retries:
        return RecoveryDecision(
            STRATEGY_REPLAN, NEEDS_REPLAN, cat_u, reason=f"replan after {cat_u}"
        )

    return RecoveryDecision(
        STRATEGY_FAIL, FAILED, cat_u, reason=detail or "no recovery path"
    )


def map_goal_status(loop_status: str) -> str:
    """Map V3.7 loop status → GoalState.status string."""
    m = {
        SUCCESS: "success",
        PARTIAL_SUCCESS: "partial_success",
        NEEDS_USER: "needs_user",
        BLOCKED: "blocked",
        FAILED: "failed",
        INTERRUPTED_STATUS: "interrupted",
        RETRY: "running",
        NEEDS_REPLAN: "running",
        RUNNING: "running",
    }
    return m.get(loop_status, (loop_status or "failed").lower())
