"""V4.5 VerificationEngine — authoritative SUCCESS / FAILURE / UNCERTAIN.

TOOL EXECUTION SUCCESS ≠ TASK SUCCESS.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from neuron.v4.types import ActionResult, VerificationOutcome
from neuron.v4.verify import expectations as exp_mod
from neuron.v4.verify import strategies
from neuron.v4.verify.types import (
    CONF_SUCCESS_MIN,
    VerificationEvidence,
    VerificationExpectation,
    VerificationMethod,
    VerificationReport,
)
from neuron.v4.verify.wait import interrupted, wait_until

log = logging.getLogger("neuron.v4.verify")


_SOFT_LEGACY_MARKERS = (
    "soft-accept",
    "soft-ok",
    "verify skipped",
    "deferred",
    "no contradiction",
    "no screen text",
    "accepted against observation",
)


class VerificationEngine:
    """Single authoritative verifier for V4 execution paths."""

    def __init__(self) -> None:
        self.last: VerificationReport | None = None
        self.stats = {
            "success": 0,
            "failure": 0,
            "uncertain": 0,
            "cancelled": 0,
            "total_latency_ms": 0.0,
            "count": 0,
        }

    def verify(
        self,
        expectation: VerificationExpectation | None = None,
        *,
        tool: str = "",
        args: dict[str, Any] | None = None,
        expected_result: str = "",
        element_id: str = "",
        intent: str = "",
        world_before=None,
        world_after=None,
        world=None,
        screen_diff=None,
        action_result: ActionResult | dict[str, Any] | None = None,
        revalidate_status: str = "",
        task_id: str = "",
        action_id: str = "",
        wait: bool = True,
        refresh: Callable[[], Any] | None = None,
        legacy_verify: Any = None,
    ) -> VerificationReport:
        """
        Verify expected effect against world evidence.

        `refresh` optional callback for targeted re-observation between polls.
        """
        t0 = time.perf_counter()
        exp = expectation or exp_mod.derive_expectation(
            tool, args, expected_result=expected_result, element_id=element_id, intent=intent
        )
        ar_dict = _action_result_dict(action_result)
        action_ok = ar_dict.get("ok")

        # Executor hard failure → FAILURE (unless we still want world check)
        if action_ok is False:
            report = VerificationReport(
                status=VerificationOutcome.FAILURE,
                action_id=action_id,
                task_id=task_id,
                expected_result=exp.description or expected_result,
                expectation=exp,
                confidence=0.9,
                reason=str(ar_dict.get("error") or ar_dict.get("message") or "action failed"),
                action_result_ok=False,
                retryable=True,
                verification_method=VerificationMethod.COMPOSITE.value,
            )
            report.evidence.add("action_ok", False, source="ActionResult")
            return self._finish(report, t0)

        world_after = world_after if world_after is not None else world

        def _once():
            wa = world_after
            if refresh is not None:
                try:
                    refreshed = refresh()
                    if refreshed is not None:
                        wa = refreshed
                except Exception:
                    pass
            return strategies.check_expectation(
                exp,
                world_after=wa,
                world_before=world_before,
                screen_diff=screen_diff,
                action_result=ar_dict,
                revalidate_status=revalidate_status,
            )

        cancelled = False
        if wait and exp.timeout_s > 0 and exp.kind.value not in ("NONE",):
            status, conf, ev, reason, method, cancelled, _elapsed = wait_until(
                _once,
                timeout_s=exp.timeout_s,
                poll_s=exp.poll_s,
                cancel_check=interrupted,
                on_poll=None,
            )
            if ev is None:
                ev = VerificationEvidence()
        else:
            status, conf, ev, reason, method = _once()
            if ev is None:
                ev = VerificationEvidence()

        status = strategies.finalize_status(status, conf)

        # Legacy soft-True cannot upgrade UNCERTAIN/FAILURE to SUCCESS
        legacy_ok = None
        if legacy_verify is not None:
            legacy_ok = bool(getattr(legacy_verify, "ok", legacy_verify))
            note = str(getattr(legacy_verify, "note", "") or "")
            if legacy_ok and any(m in note.lower() for m in _SOFT_LEGACY_MARKERS):
                if status is VerificationOutcome.SUCCESS:
                    # Demote if only soft legacy supported it without world SUCCESS evidence
                    pass
                elif status is VerificationOutcome.UNCERTAIN:
                    reason = f"{reason}; legacy soft-ok ignored"
            if legacy_ok is False and status is VerificationOutcome.SUCCESS:
                # Conflicting: world says success, legacy fail — keep world but note
                ev.conflicts.append("legacy_fail_world_success")

        # ActionResult ok alone never forces SUCCESS
        if status is VerificationOutcome.SUCCESS and conf < CONF_SUCCESS_MIN:
            status = VerificationOutcome.UNCERTAIN
            reason = f"confidence {conf:.2f} below SUCCESS threshold"

        before_fp = ""
        after_fp = ""
        try:
            if world_before is not None:
                cur = getattr(world_before, "current", world_before)
                before_fp = getattr(cur, "ensure_fingerprint", lambda: "")() or getattr(cur, "fingerprint", "") or ""
            if world_after is not None:
                cur = getattr(world_after, "current", world_after)
                after_fp = getattr(cur, "ensure_fingerprint", lambda: "")() or getattr(cur, "fingerprint", "") or ""
        except Exception:
            pass

        if cancelled:
            status = VerificationOutcome.UNCERTAIN
            reason = "verification cancelled"
            self.stats["cancelled"] += 1

        report = VerificationReport(
            status=status,
            action_id=action_id,
            task_id=task_id,
            expected_result=exp.description or expected_result,
            expectation=exp,
            evidence=ev if isinstance(ev, VerificationEvidence) else VerificationEvidence(),
            confidence=float(conf),
            reason=reason,
            before_snapshot_id=str(before_fp)[:32],
            after_snapshot_id=str(after_fp)[:32],
            verification_method=method,
            retryable=status is not VerificationOutcome.SUCCESS,
            cancelled=cancelled,
            action_result_ok=action_ok if isinstance(action_ok, bool) else None,
            legacy_ok=legacy_ok,
        )
        return self._finish(report, t0)

    def verify_grounded_action(
        self,
        grounded,
        *,
        world_before=None,
        world_after=None,
        world=None,
        screen_diff=None,
        action_result=None,
        task_id: str = "",
        wait: bool = True,
        refresh=None,
    ) -> VerificationReport:
        exp = exp_mod.from_grounded_action(grounded)
        return self.verify(
            exp,
            tool=getattr(grounded, "tool", "") or "",
            args=getattr(grounded, "arguments", None) or {},
            expected_result=getattr(grounded, "expected_result", "") or "",
            element_id=getattr(grounded, "element_id", "") or "",
            world_before=world_before,
            world_after=world_after,
            world=world,
            screen_diff=screen_diff,
            action_result=action_result,
            task_id=task_id,
            wait=wait,
            refresh=refresh,
        )

    def verify_step(
        self,
        step: dict[str, Any],
        *,
        world_before=None,
        world_after=None,
        world=None,
        screen_diff=None,
        action_result=None,
        task_id: str = "",
        wait: bool = True,
        refresh=None,
        use_legacy: bool = False,
    ) -> VerificationReport:
        exp = exp_mod.from_step(step)
        legacy = None
        if use_legacy:
            try:
                from neuron.brain import verifier as brain_verifier
                entry = _action_result_dict(action_result)
                # Evidence only — soft legacy cannot force SUCCESS
                legacy = brain_verifier.verify_execution_step(step, entry, strict=True)
            except Exception:
                legacy = None
        return self.verify(
            exp,
            tool=str(step.get("action") or ""),
            args=step.get("args") if isinstance(step.get("args"), dict) else {},
            expected_result=str(step.get("expected_result") or ""),
            world_before=world_before,
            world_after=world_after,
            world=world,
            screen_diff=screen_diff,
            action_result=action_result,
            task_id=task_id,
            wait=wait,
            refresh=refresh,
            legacy_verify=legacy,
        )

    def verify_fact(
        self,
        expectation: VerificationExpectation,
        *,
        world=None,
        task_id: str = "",
    ) -> VerificationReport:
        """Read-only fact check (smoke) — no wait."""
        return self.verify(expectation, world=world, task_id=task_id, wait=False)

    def _finish(self, report: VerificationReport, t0: float) -> VerificationReport:
        report.latency_ms = (time.perf_counter() - t0) * 1000
        self.last = report
        self.stats["count"] += 1
        self.stats["total_latency_ms"] += report.latency_ms
        key = report.status.value.lower()
        if key in self.stats:
            self.stats[key] += 1
        log.info(
            "[VERIFY][%s][%s] status=%s method=%s conf=%.2f ms=%.1f reason=%s evidence=%s",
            report.task_id or "-",
            report.action_id,
            report.status.value,
            report.verification_method,
            report.confidence,
            report.latency_ms,
            (report.reason or "")[:120],
            report.evidence.summary(),
        )
        return report


def _action_result_dict(action_result) -> dict[str, Any]:
    if action_result is None:
        return {}
    if isinstance(action_result, ActionResult):
        return {
            "ok": action_result.ok,
            "message": action_result.message,
            "error": action_result.error,
            "state": dict(action_result.state or {}),
        }
    if isinstance(action_result, dict):
        return {
            "ok": action_result.get("ok"),
            "message": str(action_result.get("out") or action_result.get("message") or ""),
            "error": str(action_result.get("error") or ""),
            "state": dict(action_result.get("state") or action_result.get("result") or {})
            if isinstance(action_result.get("state") or action_result.get("result"), dict)
            else {},
            "process": action_result.get("process"),
        }
    return {"ok": bool(getattr(action_result, "ok", getattr(action_result, "success", None)))}


_ENGINE: VerificationEngine | None = None


def get_verification_engine() -> VerificationEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = VerificationEngine()
    return _ENGINE


def reset_verification_engine() -> None:
    global _ENGINE
    _ENGINE = None


__all__ = [
    "VerificationEngine",
    "get_verification_engine",
    "reset_verification_engine",
]
