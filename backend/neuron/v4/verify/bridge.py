"""Bridge OPAVR VerifyResult ↔ V4 VerificationReport without breaking V3 API."""

from __future__ import annotations

from typing import Any

from neuron.v4.types import VerificationOutcome
from neuron.v4.verify.types import VerificationEvidence, VerificationReport


_SOFT = (
    "soft-accept",
    "soft-ok",
    "verify skipped",
    "deferred",
    "no contradiction",
    "no screen text",
    "accepted against observation",
    "moved; verify skipped",
)


def map_legacy_verify_result(legacy: Any, *, action_result_ok: bool | None = None) -> VerificationReport:
    """
    Map brain.verifier.VerifyResult → VerificationReport.

    Soft-True notes → UNCERTAIN (never SUCCESS).
    Hard False → FAILURE.
    Hard True with substance → SUCCESS (conservative).
    """
    if legacy is None:
        return VerificationReport(
            status=VerificationOutcome.UNCERTAIN,
            reason="no legacy verify result",
            action_result_ok=action_result_ok,
            verification_method="LEGACY_BRIDGE",
        )
    ok = bool(getattr(legacy, "ok", False))
    note = str(getattr(legacy, "note", "") or "")
    evidence_raw = getattr(legacy, "evidence", None) or {}
    ev = VerificationEvidence()
    if isinstance(evidence_raw, dict):
        for k, v in list(evidence_raw.items())[:12]:
            ev.add(str(k), v, source="legacy")
    ev.add("legacy_note", note[:120], source="legacy")

    if not ok:
        return VerificationReport(
            status=VerificationOutcome.FAILURE,
            reason=note or "legacy verify failed",
            evidence=ev,
            confidence=0.8,
            action_result_ok=action_result_ok,
            legacy_ok=False,
            verification_method="LEGACY_BRIDGE",
        )

    note_l = note.lower()
    if any(m in note_l for m in _SOFT):
        return VerificationReport(
            status=VerificationOutcome.UNCERTAIN,
            reason=f"legacy soft-ok → UNCERTAIN: {note[:120]}",
            evidence=ev,
            confidence=0.4,
            action_result_ok=action_result_ok,
            legacy_ok=True,
            verification_method="LEGACY_BRIDGE",
            retryable=True,
        )

    # Hard True — still require some note substance; empty "ok" is weak
    if not note.strip() or note.strip().lower() in ("ok", "done", "done."):
        return VerificationReport(
            status=VerificationOutcome.UNCERTAIN,
            reason="legacy ok without evidence",
            evidence=ev,
            confidence=0.35,
            action_result_ok=action_result_ok,
            legacy_ok=True,
            verification_method="LEGACY_BRIDGE",
        )

    return VerificationReport(
        status=VerificationOutcome.SUCCESS,
        reason=note,
        evidence=ev,
        confidence=0.7,
        action_result_ok=action_result_ok,
        legacy_ok=True,
        verification_method="LEGACY_BRIDGE",
    )


def report_to_legacy_tuple(report: VerificationReport) -> tuple[bool, str]:
    """For GoalState / Trace that still expect (ok, note). UNCERTAIN → False."""
    return report.to_legacy_ok(), report.reason


__all__ = ["map_legacy_verify_result", "report_to_legacy_tuple"]
