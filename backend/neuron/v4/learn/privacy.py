"""Privacy + volatile filters for procedure candidates.

PROCEDURE_PRIVACY_VIOLATION_COUNT = count of *persisted* unsafe procedures
(should stay 0). Rejected candidates do not increment it.
"""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.learn.types import COORDINATE_KEYS, ProcedureCandidate, ProcedureStep

PROCEDURE_PRIVACY_VIOLATION_COUNT = 0
PROCEDURE_PRIVACY_REJECT_COUNT = 0

_VOLATILE_KEYS = frozenset({
    "hwnd", "pid", "process_id", "element_id", "runtime_id", "handle",
    "session", "session_id", "cookie", "csrf", "nonce",
})

_SESSION_URL = re.compile(r"(?i)(access_token|id_token|auth|session|sid)=[^&\s]+")
_OCR_BLOB = re.compile(r"(?i)^(ocr|screenshot|clipboard)_")


def reset_privacy_metrics() -> None:
    global PROCEDURE_PRIVACY_VIOLATION_COUNT, PROCEDURE_PRIVACY_REJECT_COUNT
    PROCEDURE_PRIVACY_VIOLATION_COUNT = 0
    PROCEDURE_PRIVACY_REJECT_COUNT = 0


def note_persisted_attempt_blocked() -> None:
    """Called when accept tried to persist unsafe content — still not a persisted violation."""
    global PROCEDURE_PRIVACY_REJECT_COUNT
    PROCEDURE_PRIVACY_REJECT_COUNT += 1


def note_persisted_violation() -> None:
    """Bug path: unsafe procedure was written. Must remain 0 in healthy runs."""
    global PROCEDURE_PRIVACY_VIOLATION_COUNT
    PROCEDURE_PRIVACY_VIOLATION_COUNT += 1


def validate_privacy(candidate: ProcedureCandidate) -> tuple[bool, str]:
    """Return (ok, reason). Rejects increment PROCEDURE_PRIVACY_REJECT_COUNT only."""
    global PROCEDURE_PRIVACY_REJECT_COUNT
    try:
        from neuron.learning import semantic as sem
    except Exception:
        sem = None

    def _reject(reason: str) -> tuple[bool, str]:
        global PROCEDURE_PRIVACY_REJECT_COUNT
        PROCEDURE_PRIVACY_REJECT_COUNT += 1
        return False, reason

    for step in candidate.steps:
        tool = (step.tool or step.capability_id or "").lower()
        if tool in ("click", "mouse_click", "drag"):
            return _reject("raw coordinate/mouse action not learnable")
        args = dict(step.arguments or {})
        for k in args:
            kl = str(k).lower()
            if kl in COORDINATE_KEYS:
                return _reject(f"coordinate key {k} cannot be durable")
            if kl in _VOLATILE_KEYS:
                return _reject(f"volatile key {k} cannot be durable")
            if _OCR_BLOB.match(kl):
                return _reject(f"ocr/clipboard blob key {k}")
        for k, v in args.items():
            s = str(v)
            if _SESSION_URL.search(s):
                return _reject("session/token URL rejected")
            if sem and sem.is_sensitive_key(str(k)):
                return _reject(f"sensitive key {k}")
            if sem and hasattr(sem, "rejects_private_field"):
                fake = {"action": tool, "args": {k: v}}
                if sem.rejects_private_field(fake):
                    return _reject("private field content")
            # Large UI dumps
            if len(s) > 400 and " " in s:
                return _reject("oversized text blob")
    return True, "ok"


def scrub_steps_for_learning(steps: list[ProcedureStep]) -> tuple[list[ProcedureStep], list[str]]:
    """Drop coordinates / scrub secrets using V3.8 semantic layer."""
    warnings: list[str] = []
    legacy = [s.to_legacy_step() for s in steps]
    try:
        from neuron.learning.semantic import sanitize_steps
        cleaned, warns = sanitize_steps(legacy, drop_coordinates=True)
        warnings.extend(warns)
    except Exception as exc:
        return steps, [str(exc)]

    out: list[ProcedureStep] = []
    for i, st in enumerate(cleaned):
        src = steps[i] if i < len(steps) else ProcedureStep()
        out.append(
            ProcedureStep(
                capability_id=src.capability_id,
                tool=str(st.get("action") or src.tool),
                arguments=dict(st.get("args") or {}),
                param_bindings=dict(src.param_bindings),
                expected_result=str(st.get("expected_result") or src.expected_result),
                verification_kind=src.verification_kind,
            )
        )
    return out, warnings


def privacy_metrics() -> dict[str, int]:
    return {
        "PROCEDURE_PRIVACY_VIOLATION_COUNT": PROCEDURE_PRIVACY_VIOLATION_COUNT,
        "PROCEDURE_PRIVACY_REJECT_COUNT": PROCEDURE_PRIVACY_REJECT_COUNT,
    }


__all__ = [
    "PROCEDURE_PRIVACY_VIOLATION_COUNT",
    "PROCEDURE_PRIVACY_REJECT_COUNT",
    "reset_privacy_metrics",
    "note_persisted_attempt_blocked",
    "note_persisted_violation",
    "validate_privacy",
    "scrub_steps_for_learning",
    "privacy_metrics",
]
