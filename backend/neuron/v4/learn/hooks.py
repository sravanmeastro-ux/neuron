"""Learning hooks — gated ingest after verified task success.

Never learns from executor-ok alone. Never bypasses AgentLoop for execution.
"""

from __future__ import annotations

import logging
from typing import Any

from neuron.v4.learn.config import procedure_learning_enabled
from neuron.v4.learn.eligibility import build_trace, is_eligible
from neuron.v4.learn.learner import PROCEDURE_DUPLICATE_COUNT, get_procedure_learner
from neuron.v4.learn.privacy import PROCEDURE_PRIVACY_VIOLATION_COUNT, privacy_metrics
from neuron.v4.learn.registry import get_procedure_registry

log = logging.getLogger("neuron.v4.learn")


def maybe_learn_from_trace(
    *,
    goal_text: str,
    steps: list[dict],
    final_status: str,
    task_verified: bool,
    cancelled: bool = False,
    blocked: bool = False,
    safety_ok: bool = True,
    intent_family: str = "",
    auto_accept: bool = False,
) -> dict[str, Any]:
    """Ingest a verified task when learning is enabled.

    Returns a status dict suitable for logs/tests. Default config: learning off.
    """
    out: dict[str, Any] = {"attempted": False, "eligible": False, "accepted": False}
    if not procedure_learning_enabled() and not auto_accept:
        out["reason"] = "procedure_learning_enabled=false"
        return out

    out["attempted"] = True
    trace = build_trace(
        goal_text=goal_text,
        steps=steps,
        final_status=final_status,
        task_verified=task_verified,
        cancelled=cancelled,
        blocked=blocked,
        safety_ok=safety_ok,
        intent_family=intent_family,
    )
    ok, reason = is_eligible(trace)
    out["eligible"] = ok
    out["eligibility_reason"] = reason
    if not ok:
        return out

    learner = get_procedure_learner()
    ingested, msg, cand = learner.ingest_trace(trace)
    out["ingest"] = msg
    out["candidate"] = cand.to_dict() if cand else None
    if not ingested or not cand or cand.rejected:
        return out

    # Auto-accept only with enough evidence (or force for tests via auto_accept + force)
    force = bool(auto_accept and cand.evidence_count >= 1 and procedure_learning_enabled() is False)
    # When learning enabled: accept when evidence threshold met
    # When tests call with auto_accept=True and learning off: allow force accept for harness
    accept_force = force or (auto_accept and cand.evidence_count >= 3)
    if cand.evidence_count >= 3 or accept_force:
        reg = get_procedure_registry()
        aok, areason, proc = reg.accept_and_register(
            cand,
            force=accept_force or cand.evidence_count >= 3,
        )
        out["accepted"] = aok
        out["accept_reason"] = areason
        out["procedure_id"] = proc.procedure_id if proc else None
        if aok and proc:
            log.info("[LEARN] registered %s", proc.procedure_id)
    return out


def learn_metrics() -> dict[str, Any]:
    learner = get_procedure_learner()
    m = {
        "PROCEDURE_DUPLICATE_COUNT": PROCEDURE_DUPLICATE_COUNT,
        "PROCEDURE_PRIVACY_VIOLATION_COUNT": PROCEDURE_PRIVACY_VIOLATION_COUNT,
        **privacy_metrics(),
        **dict(learner.stats),
        "procedure_learning_enabled": procedure_learning_enabled(),
        "n_procedures": len(learner.definitions),
    }
    return m


__all__ = ["maybe_learn_from_trace", "learn_metrics"]
