"""Evidence-driven failure diagnosis from VerificationReport + ActionResult."""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.types import VerificationOutcome
from neuron.v4.recover.types import FailureCategory, FailureDiagnosis


_V3_TO_V4 = {
    "ELEMENT_NOT_FOUND": FailureCategory.TARGET_NOT_FOUND,
    "WINDOW_NOT_FOUND": FailureCategory.WINDOW_FAILURE,
    "APP_NOT_RUNNING": FailureCategory.APPLICATION_NOT_READY,
    "PAGE_NOT_LOADED": FailureCategory.PAGE_NOT_LOADED,
    "POPUP_DETECTED": FailureCategory.POPUP_DETECTED,
    "FOCUS_LOST": FailureCategory.FOCUS_FAILURE,
    "WRONG_WINDOW": FailureCategory.FOCUS_FAILURE,
    "WRONG_MONITOR": FailureCategory.WRONG_MONITOR,
    "ACTION_TIMEOUT": FailureCategory.TIMEOUT,
    "VERIFICATION_FAILED": FailureCategory.VERIFICATION_FAILURE,
    "PERMISSION_REQUIRED": FailureCategory.PERMISSION_DENIED,
    "AMBIGUOUS_TARGET": FailureCategory.TARGET_AMBIGUOUS,
    "POLICY_BLOCKED": FailureCategory.SAFETY_DENIED,
    "INTERRUPTED": FailureCategory.USER_CANCELLED,
    "UNKNOWN": FailureCategory.UNKNOWN_FAILURE,
}


def diagnose(
    *,
    verification=None,
    action_result: dict[str, Any] | None = None,
    tool: str = "",
    args: dict[str, Any] | None = None,
    legacy_diagnosis: dict[str, Any] | None = None,
    resolution_status: str = "",
    world_before_fp: str = "",
    world_after_fp: str = "",
    interrupted: bool = False,
    task_id: str = "",
    action_id: str = "",
    subgoal_id: str = "",
) -> FailureDiagnosis:
    """
    Prefer VerificationReport evidence; enrich with legacy diagnose_failure category.
    """
    args = dict(args or {})
    ar = dict(action_result or {})
    reason = ""
    vstatus = ""
    evidence: dict[str, Any] = {}
    conf = 0.5

    if interrupted or ar.get("interrupted"):
        return FailureDiagnosis(
            task_id=task_id,
            action_id=action_id,
            subgoal_id=subgoal_id,
            category=FailureCategory.USER_CANCELLED,
            reason="interrupted by user",
            verification_status="CANCELLED",
            tool=tool,
            args=args,
            retryable=False,
            confidence=1.0,
            v3_category="INTERRUPTED",
        )

    if verification is not None:
        status = getattr(verification, "status", None) or getattr(verification, "outcome", None)
        if hasattr(status, "value"):
            vstatus = status.value
        else:
            vstatus = str(status or "")
        reason = str(getattr(verification, "reason", None) or getattr(verification, "detail", "") or "")
        ev = getattr(verification, "evidence", None)
        if ev is not None and hasattr(ev, "to_dict"):
            evidence = ev.to_dict().get("facts") or {}
        elif isinstance(ev, dict):
            evidence = dict(ev.get("facts") or ev)
        conf = float(getattr(verification, "confidence", 0.5) or 0.5)
        world_before_fp = world_before_fp or str(getattr(verification, "before_snapshot_id", "") or "")
        world_after_fp = world_after_fp or str(getattr(verification, "after_snapshot_id", "") or "")

    # Safety / permission from args or notes (avoid matching "to confirm app open")
    blob = f"{reason} {ar.get('error') or ''} {ar.get('message') or ''}".lower()
    if re.search(r"\b(policy[_\s-]?blocked|safety denied|blocked by safety)\b", blob):
        return _diag(
            FailureCategory.SAFETY_DENIED, reason or "safety denied", vstatus,
            evidence, tool, args, False, 0.95, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "POLICY_BLOCKED",
        )
    if re.search(
        r"\b(needs?\s+confirm|confirmation required|permission denied|permission required)\b",
        blob,
    ):
        return _diag(
            FailureCategory.PERMISSION_DENIED, reason or "permission required", vstatus,
            evidence, tool, args, False, 0.9, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "PERMISSION_REQUIRED",
            ask="I need your confirmation to continue.",
        )

    # Prefer OPAVR/V3 diagnose_failure taxonomy when present (keeps POPUP, ELEMENT_NOT_FOUND, …)
    legacy_pref = _prefer_legacy(
        legacy_diagnosis,
        reason=reason,
        vstatus=vstatus,
        evidence=evidence,
        tool=tool,
        args=args,
        task_id=task_id,
        action_id=action_id,
        subgoal_id=subgoal_id,
        before_fp=world_before_fp,
        after_fp=world_after_fp,
        conf=conf,
    )
    if legacy_pref is not None:
        return legacy_pref

    # Popup cues from verification text (even without legacy)
    if any(x in blob for x in ("popup", "cookie", "consent", "modal", "overlay blocking")):
        return _diag(
            FailureCategory.POPUP_DETECTED, reason or "popup detected", vstatus or "FAILURE",
            evidence, tool, args, True, 0.85, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "POPUP_DETECTED",
        )

    # Resolution statuses
    rs = (resolution_status or "").upper()
    if rs == "AMBIGUOUS":
        return _diag(
            FailureCategory.TARGET_AMBIGUOUS, "ambiguous target", vstatus, evidence,
            tool, args, False, 0.85, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "AMBIGUOUS_TARGET",
            ask="Which element did you mean?",
        )
    if rs in ("STALE_WORLD",):
        return _diag(
            FailureCategory.TARGET_STALE, "stale world / target", vstatus, evidence,
            tool, args, True, 0.8, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "ELEMENT_NOT_FOUND",
        )
    if rs == "NOT_FOUND":
        return _diag(
            FailureCategory.TARGET_NOT_FOUND, "target not found", vstatus, evidence,
            tool, args, True, 0.85, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "ELEMENT_NOT_FOUND",
        )
    if rs == "INSUFFICIENT_CONTEXT":
        return _diag(
            FailureCategory.CONTEXT_INSUFFICIENT, "insufficient context", vstatus, evidence,
            tool, args, True, 0.7, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "AMBIGUOUS_TARGET",
            ask="I need more context to continue.",
        )

    # Executor-level
    if ar.get("ok") is False:
        err = str(ar.get("error") or ar.get("message") or "tool failed")
        if "unknown tool" in err.lower() or "not registered" in err.lower():
            return _diag(
                FailureCategory.INVALID_TOOL, err, vstatus, evidence, tool, args, False,
                0.9, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "UNKNOWN",
            )
        if "invalid" in err.lower() and "arg" in err.lower():
            return _diag(
                FailureCategory.INVALID_ARGUMENTS, err, vstatus, evidence, tool, args, True,
                0.85, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "UNKNOWN",
            )
        if "timeout" in err.lower() or "timed out" in err.lower():
            return _diag(
                FailureCategory.TIMEOUT, err, vstatus, evidence, tool, args, True,
                0.8, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "ACTION_TIMEOUT",
            )
        return _diag(
            FailureCategory.TOOL_FAILURE, err, vstatus, evidence, tool, args, True,
            0.75, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "UNKNOWN",
        )

    # Verification-driven
    status_enum = None
    if verification is not None:
        status_enum = getattr(verification, "status", None) or getattr(verification, "outcome", None)

    if status_enum is VerificationOutcome.UNCERTAIN or vstatus == "UNCERTAIN":
        # Specialize uncertain
        if evidence.get("process_without_window") or "window not observed" in reason.lower():
            return _diag(
                FailureCategory.APPLICATION_NOT_READY, reason or "app not ready",
                "UNCERTAIN", evidence, tool, args, True, conf, task_id, action_id, subgoal_id,
                world_before_fp, world_after_fp, "APP_NOT_RUNNING",
            )
        if "media fullscreen" in reason.lower() or "fullscreen" in reason.lower():
            return _diag(
                FailureCategory.VERIFICATION_UNCERTAIN, reason or "fullscreen uncertain",
                "UNCERTAIN", evidence, tool, args, True, conf, task_id, action_id, subgoal_id,
                world_before_fp, world_after_fp, "VERIFICATION_FAILED",
            )
        if "no observable" in reason.lower() or "no change" in reason.lower() or "trivial" in reason.lower():
            return _diag(
                FailureCategory.ACTION_NO_EFFECT, reason or "action no effect",
                "UNCERTAIN", evidence, tool, args, True, conf, task_id, action_id, subgoal_id,
                world_before_fp, world_after_fp, "VERIFICATION_FAILED",
            )
        return _diag(
            FailureCategory.VERIFICATION_UNCERTAIN, reason or "verification uncertain",
            "UNCERTAIN", evidence, tool, args, True, conf, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "VERIFICATION_FAILED",
        )

    if status_enum is VerificationOutcome.FAILURE or vstatus == "FAILURE":
        # Evidence specialization
        if "foreground" in reason.lower() or evidence.get("active_application"):
            tool_l = (tool or "").lower()
            if "focus" in tool_l or "foreground" in reason.lower():
                return _diag(
                    FailureCategory.FOCUS_FAILURE, reason, "FAILURE", evidence, tool, args, True,
                    conf, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "FOCUS_LOST",
                )
        if "monitor" in reason.lower() or evidence.get("after_monitor_id") is not None:
            return _diag(
                FailureCategory.WRONG_MONITOR, reason, "FAILURE", evidence, tool, args, True,
                conf, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "WRONG_MONITOR",
            )
        if "window not found" in reason.lower() or evidence.get("window_found") is False:
            if "open" in (tool or "").lower():
                return _diag(
                    FailureCategory.APPLICATION_NOT_READY, reason, "FAILURE", evidence, tool, args, True,
                    conf, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "APP_NOT_RUNNING",
                )
            return _diag(
                FailureCategory.WINDOW_FAILURE, reason, "FAILURE", evidence, tool, args, True,
                conf, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "WINDOW_NOT_FOUND",
            )
        if "url" in reason.lower():
            return _diag(
                FailureCategory.PAGE_NOT_LOADED, reason, "FAILURE", evidence, tool, args, True,
                conf, task_id, action_id, subgoal_id, world_before_fp, world_after_fp, "PAGE_NOT_LOADED",
            )
        return _diag(
            FailureCategory.VERIFICATION_FAILURE, reason or "verification failed", "FAILURE",
            evidence, tool, args, True, conf, task_id, action_id, subgoal_id,
            world_before_fp, world_after_fp, "VERIFICATION_FAILED",
        )

    return _diag(
        FailureCategory.UNKNOWN_FAILURE,
        reason or "unknown failure",
        vstatus or "FAILURE",
        evidence,
        tool,
        args,
        True,
        0.4,
        task_id,
        action_id,
        subgoal_id,
        world_before_fp,
        world_after_fp,
        "UNKNOWN",
    )


def _diag(
    category: FailureCategory,
    reason: str,
    vstatus: str,
    evidence: dict,
    tool: str,
    args: dict,
    retryable: bool,
    confidence: float,
    task_id: str,
    action_id: str,
    subgoal_id: str,
    before_fp: str,
    after_fp: str,
    v3: str,
    ask: str = "",
) -> FailureDiagnosis:
    return FailureDiagnosis(
        task_id=task_id,
        action_id=action_id,
        subgoal_id=subgoal_id,
        category=category,
        reason=reason,
        verification_status=vstatus,
        evidence=dict(evidence or {}),
        world_before_fp=before_fp,
        world_after_fp=after_fp,
        tool=tool,
        args=dict(args or {}),
        retryable=retryable,
        confidence=confidence,
        v3_category=v3,
        ask_prompt=ask,
    )


_CAUSE_TO_V3 = {
    "interrupted": "INTERRUPTED",
    "timeout": "ACTION_TIMEOUT",
    "needs_confirm": "PERMISSION_REQUIRED",
    "policy_blocked": "POLICY_BLOCKED",
    "ambiguous": "AMBIGUOUS_TARGET",
    "popup": "POPUP_DETECTED",
    "monitor_mismatch": "WRONG_MONITOR",
    "wrong_window": "WRONG_WINDOW",
    "focus": "FOCUS_LOST",
    "app_not_present": "APP_NOT_RUNNING",
    "window_missing": "WINDOW_NOT_FOUND",
    "target_not_found": "ELEMENT_NOT_FOUND",
    "browser_state_mismatch": "PAGE_NOT_LOADED",
    "verification_failed": "VERIFICATION_FAILED",
    "no_foreground_context": "FOCUS_LOST",
}


def _prefer_legacy(
    legacy_diagnosis: dict[str, Any] | None,
    *,
    reason: str,
    vstatus: str,
    evidence: dict,
    tool: str,
    args: dict,
    task_id: str,
    action_id: str,
    subgoal_id: str,
    before_fp: str,
    after_fp: str,
    conf: float,
) -> FailureDiagnosis | None:
    if not isinstance(legacy_diagnosis, dict) or not legacy_diagnosis:
        return None
    cat = str(legacy_diagnosis.get("category") or "").upper()
    cause = str(legacy_diagnosis.get("cause") or "").lower()
    if (not cat or cat == "UNKNOWN") and cause:
        cat = _CAUSE_TO_V3.get(cause, "")
    if not cat or cat == "UNKNOWN":
        return None
    mapped = _V3_TO_V4.get(cat)
    if mapped is None:
        return None
    # Skip only if legacy is totally generic and we have no cause — already filtered
    detail = str(legacy_diagnosis.get("detail") or reason or cat)
    retryable = mapped not in (
        FailureCategory.SAFETY_DENIED,
        FailureCategory.USER_CANCELLED,
        FailureCategory.PERMISSION_DENIED,
    )
    return _diag(
        mapped,
        detail,
        vstatus or "FAILURE",
        evidence,
        tool or str(legacy_diagnosis.get("action") or ""),
        args,
        retryable,
        max(0.7, conf),
        task_id,
        action_id,
        subgoal_id,
        before_fp,
        after_fp,
        cat,
        ask=str(legacy_diagnosis.get("ask_prompt") or ""),
    )


__all__ = ["diagnose"]
