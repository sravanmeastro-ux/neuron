"""ProcedureLearner — candidates from verified traces; versioning + dedup.

PROCEDURE_DUPLICATE_COUNT increments only when an equivalent procedure would
be registered as a *new* id (bug). Correct merges keep the count at 0.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from neuron.v4.learn import eligibility, generalize, privacy
from neuron.v4.learn.types import (
    MIN_EVIDENCE_FOR_AUTO_ACCEPT,
    ProcedureCandidate,
    ProcedureDefinition,
    ProcedureSource,
    VerifiedTaskTrace,
)

log = logging.getLogger("neuron.v4.learn")

PROCEDURE_DUPLICATE_COUNT = 0

_LEARNER: "ProcedureLearner | None" = None


def reset_duplicate_metrics() -> None:
    global PROCEDURE_DUPLICATE_COUNT
    PROCEDURE_DUPLICATE_COUNT = 0


class ProcedureLearner:
    def __init__(self) -> None:
        self.traces: list[VerifiedTaskTrace] = []
        self.candidates: list[ProcedureCandidate] = []
        self.definitions: dict[str, ProcedureDefinition] = {}
        self.versions: dict[str, list[ProcedureDefinition]] = {}
        self.by_fingerprint: dict[str, str] = {}
        self.stats = {
            "traces_seen": 0,
            "eligible": 0,
            "rejected_eligibility": 0,
            "candidates": 0,
            "accepted": 0,
            "rejected_privacy": 0,
            "rejected_validation": 0,
            "duplicates_merged": 0,
        }

    def ingest_trace(self, trace: VerifiedTaskTrace) -> tuple[bool, str, ProcedureCandidate | None]:
        self.stats["traces_seen"] += 1
        ok, reason = eligibility.is_eligible(trace)
        if not ok:
            self.stats["rejected_eligibility"] += 1
            log.info("[LEARN] ineligible: %s", reason)
            return False, reason, None
        self.stats["eligible"] += 1
        self.traces.append(trace)
        if len(self.traces) > 40:
            self.traces = self.traces[-40:]

        similar = [t for t in self.traces if t.intent_family == trace.intent_family]
        cand = generalize.generalize_traces(similar if similar else [trace])
        if cand is None:
            return False, "generalization failed", None

        priv_ok, priv_reason = privacy.validate_privacy(cand)
        if not priv_ok:
            cand.rejected = True
            cand.reject_reason = priv_reason
            cand.privacy_ok = False
            self.stats["rejected_privacy"] += 1
            log.info("[LEARN] privacy reject: %s", priv_reason)
            return False, priv_reason, cand

        scrubbed, _warns = privacy.scrub_steps_for_learning(cand.steps)
        cand.steps = scrubbed
        if len(cand.steps) < 2:
            cand.rejected = True
            cand.reject_reason = "insufficient semantic steps after scrub"
            self.stats["rejected_validation"] += 1
            return False, cand.reject_reason, cand

        existing_id = self.by_fingerprint.get(cand.fingerprint)
        if existing_id and existing_id in self.definitions:
            self.stats["duplicates_merged"] += 1
            proc = self.definitions[existing_id]
            proc.evidence_count += 1
            proc.confidence = min(0.95, proc.confidence + 0.05)
            proc.updated_at = time.time()
            # Refresh candidate evidence for callers
            cand.evidence_count = proc.evidence_count
            cand.confidence = proc.confidence
            log.info("[LEARN] merged evidence into %s", existing_id)
            return True, "merged_duplicate", cand

        self.candidates.append(cand)
        if len(self.candidates) > 30:
            self.candidates = self.candidates[-30:]
        self.stats["candidates"] += 1
        log.info(
            "[LEARN] candidate %s evidence=%d conf=%.2f",
            cand.name,
            cand.evidence_count,
            cand.confidence,
        )
        return True, "candidate", cand

    def accept_candidate(
        self,
        candidate: ProcedureCandidate,
        *,
        force: bool = False,
    ) -> tuple[bool, str, ProcedureDefinition | None]:
        if candidate.rejected or not candidate.privacy_ok:
            return False, candidate.reject_reason or "rejected", None
        # Re-validate privacy before accept (never persist violations)
        priv_ok, priv_reason = privacy.validate_privacy(candidate)
        if not priv_ok:
            privacy.note_persisted_attempt_blocked()
            return False, priv_reason, None
        if not force and candidate.evidence_count < MIN_EVIDENCE_FOR_AUTO_ACCEPT:
            return False, (
                f"need {MIN_EVIDENCE_FOR_AUTO_ACCEPT} evidence "
                f"(have {candidate.evidence_count})"
            ), None

        try:
            from neuron.v4.capability import get_capability_catalog
            cat = get_capability_catalog()
            for st in candidate.steps:
                tool = st.tool or st.capability_id
                if not tool:
                    continue
                if cat.canonical_tool(tool) or cat.supports(tool):
                    continue
                from neuron.brain import tool_registry as tr
                tr.ensure_bootstrapped()
                if not tr.is_registered(tool):
                    self.stats["rejected_validation"] += 1
                    return False, f"unknown capability {tool}", None
        except Exception:
            pass

        fp = candidate.fingerprint
        existing_id = self.by_fingerprint.get(fp)
        if existing_id and existing_id in self.definitions:
            proc = self.definitions[existing_id]
            new_ver = ProcedureDefinition(
                procedure_id=existing_id,
                name=candidate.name,
                description=f"Learned {candidate.intent_family}",
                intent_family=candidate.intent_family,
                parameters=list(candidate.parameters),
                steps=list(candidate.steps),
                preconditions=list(candidate.preconditions),
                completion_criteria=list(candidate.completion_criteria),
                risk_summary=candidate.risk_summary,
                source=ProcedureSource.LEARNED,
                version=proc.version + 1,
                aliases=list(candidate.aliases),
                enabled=True,
                confidence=candidate.confidence,
                evidence_count=proc.evidence_count + max(1, candidate.evidence_count),
                created_at=proc.created_at,
            )
            self.versions.setdefault(fp, []).append(new_ver)
            self.definitions[existing_id] = new_ver
            self.stats["accepted"] += 1
            self.stats["duplicates_merged"] += 1
            return True, f"versioned v{new_ver.version}", new_ver

        # Detect accidental duplicate id collision
        safe = re.sub(r"[^a-z0-9_]+", "_", (candidate.name or "workflow").lower()).strip("_")
        proc_id = f"learned.{safe or 'workflow'}"
        if proc_id in self.definitions:
            other = self.definitions[proc_id]
            if other.fingerprint() != fp:
                # Different structure same display name → suffix
                proc_id = f"{proc_id}_v{int(time.time()) % 10000}"
            else:
                global PROCEDURE_DUPLICATE_COUNT
                PROCEDURE_DUPLICATE_COUNT += 1
                return False, "duplicate procedure id", None

        proc = ProcedureDefinition(
            procedure_id=proc_id,
            name=candidate.name,
            description=f"Learned {candidate.intent_family}",
            intent_family=candidate.intent_family,
            parameters=list(candidate.parameters),
            steps=list(candidate.steps),
            preconditions=list(candidate.preconditions),
            completion_criteria=list(candidate.completion_criteria),
            risk_summary=candidate.risk_summary,
            source=ProcedureSource.LEARNED,
            version=1,
            aliases=list(candidate.aliases),
            enabled=True,
            confidence=candidate.confidence,
            evidence_count=candidate.evidence_count,
        )
        self.definitions[proc.procedure_id] = proc
        self.by_fingerprint[fp] = proc.procedure_id
        self.versions.setdefault(fp, [proc])
        self.stats["accepted"] += 1
        log.info("[PROCEDURE] accepted %s v1", proc.procedure_id)
        return True, "accepted", proc

    def get(self, procedure_id: str) -> ProcedureDefinition | None:
        return self.definitions.get(procedure_id)

    def get_version(self, procedure_id: str, version: int) -> ProcedureDefinition | None:
        for fp, vers in self.versions.items():
            for v in vers:
                if v.procedure_id == procedure_id and v.version == version:
                    return v
        p = self.definitions.get(procedure_id)
        if p and p.version == version:
            return p
        return None

    def list_enabled(self) -> list[ProcedureDefinition]:
        return [p for p in self.definitions.values() if p.enabled]

    def list_all(self) -> list[ProcedureDefinition]:
        return list(self.definitions.values())

    def disable(self, procedure_id: str) -> bool:
        p = self.definitions.get(procedure_id)
        if not p:
            return False
        p.enabled = False
        p.updated_at = time.time()
        return True

    def enable(self, procedure_id: str) -> bool:
        p = self.definitions.get(procedure_id)
        if not p:
            return False
        p.enabled = True
        p.updated_at = time.time()
        return True

    def delete(self, procedure_id: str) -> bool:
        p = self.definitions.pop(procedure_id, None)
        if not p:
            return False
        self.by_fingerprint = {k: v for k, v in self.by_fingerprint.items() if v != procedure_id}
        return True

    def rename_alias(self, procedure_id: str, alias: str) -> bool:
        p = self.definitions.get(procedure_id)
        if not p or not alias:
            return False
        a = alias.strip().lower()
        if a and a not in [x.lower() for x in p.aliases]:
            p.aliases.append(a)
            p.updated_at = time.time()
        return True

    def match(self, text: str) -> ProcedureDefinition | None:
        t = (text or "").lower().strip()
        if not t:
            return None
        best: ProcedureDefinition | None = None
        best_score = 0.0
        for p in self.list_enabled():
            score = 0.0
            if p.name.lower() in t or t in p.name.lower():
                score = 50 + len(p.name)
            for a in p.aliases:
                al = a.lower()
                if al in t or t in al:
                    score = max(score, 40 + len(al))
            if p.intent_family and p.intent_family.replace("_", " ") in t:
                score = max(score, 30)
            if score > best_score:
                best = p
                best_score = score
        return best if best_score >= 30 else None

    def note_execution(self, procedure_id: str, *, verify: str, recovery: bool = False) -> None:
        p = self.definitions.get(procedure_id)
        if not p:
            return
        p.attempts += 1
        v = (verify or "").upper()
        if v == "SUCCESS":
            p.verified_successes += 1
        elif v == "FAILURE":
            p.verified_failures += 1
        elif v == "UNCERTAIN":
            p.uncertain_outcomes += 1
        if recovery:
            p.recovery_required += 1
        # Confidence from verified success rate
        if p.attempts >= 2:
            rate = p.verified_successes / max(1, p.attempts)
            p.confidence = min(0.95, 0.4 + 0.5 * rate)

    def expand_to_plan_steps(
        self,
        procedure_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        p = self.definitions.get(procedure_id)
        if not p or not p.enabled:
            return []
        return [s.to_legacy_step(params) for s in p.steps]


def get_procedure_learner() -> ProcedureLearner:
    global _LEARNER
    if _LEARNER is None:
        _LEARNER = ProcedureLearner()
    return _LEARNER


def reset_procedure_learner() -> ProcedureLearner:
    global _LEARNER
    reset_duplicate_metrics()
    privacy.reset_privacy_metrics()
    _LEARNER = ProcedureLearner()
    return _LEARNER


__all__ = [
    "ProcedureLearner",
    "get_procedure_learner",
    "reset_procedure_learner",
    "PROCEDURE_DUPLICATE_COUNT",
    "reset_duplicate_metrics",
]
