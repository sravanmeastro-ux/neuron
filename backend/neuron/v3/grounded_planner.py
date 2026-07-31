"""V3.6 grounded planner façade — wraps neuron.brain.planner.

Deterministic capabilities stay on CapabilityRouter; this module is for
LLM planning with grounding + validation.
"""

from __future__ import annotations

from typing import Any

from neuron.brain.planner import (
    build_grounding,
    plan,
    plan_from_llm_raw,
    replan,
)
from neuron.v3.plan_validator import (
    PlanValidation,
    looks_like_injection,
    quarantine_untrusted,
    validate_plan,
)


def grounded_plan(
    user_goal: str,
    *,
    context: str = "",
    world_state: str = "",
    reference: str | dict | None = None,
    observation: str = "",
    recent_results: str = "",
    normalized: str = "",
) -> dict | None:
    """Plan with explicit grounding channels (calls Ollama when enabled)."""
    return plan(
        user_goal,
        context=context,
        normalized=normalized,
        world_state=world_state,
        reference=reference,
        observation=observation,
        recent_results=recent_results,
        validate=True,
    )


def validate_or_reject(raw: Any) -> PlanValidation:
    return validate_plan(raw, allow_empty=True, require_structured=True)


__all__ = [
    "grounded_plan",
    "build_grounding",
    "plan",
    "replan",
    "plan_from_llm_raw",
    "validate_plan",
    "validate_or_reject",
    "PlanValidation",
    "quarantine_untrusted",
    "looks_like_injection",
]
