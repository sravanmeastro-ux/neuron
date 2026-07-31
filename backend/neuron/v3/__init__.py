"""NEURON V3 package — thin façades over existing V2 neuron modules."""

from __future__ import annotations

from neuron.v3.capability_router import Capability, RouteResult, route
from neuron.v3.context_engine import ContextEngine, get_engine, reset_engine
from neuron.v3.element_resolver import ElementHit, ElementResolver, resolve_element
from neuron.v3.grounded_planner import grounded_plan, validate_or_reject
from neuron.v3.loop_types import (
    FAILURE_CATEGORIES,
    Diagnosis,
    RecoveryDecision,
    decide_recovery,
)
from neuron.v3.perception_engine import (
    PerceptionEngine,
    observe,
    ui_candidates_for,
    wants_ui_candidates,
)
from neuron.v3.perception_types import Observation, PerceivedElement
from neuron.v3.plan_validator import PlanValidation, validate_plan
from neuron.v3.reference_resolver import (
    ReferenceResolution,
    needs_resolution,
    resolve_reference,
)
from neuron.v3.tool_registry import PRIMITIVES, ensure_primitives, validate_args
from neuron.v3.world_state import AttemptedAction, WorldState

__all__ = [
    "Capability",
    "RouteResult",
    "route",
    "ContextEngine",
    "get_engine",
    "reset_engine",
    "WorldState",
    "AttemptedAction",
    "ReferenceResolution",
    "needs_resolution",
    "resolve_reference",
    "PerceptionEngine",
    "Observation",
    "PerceivedElement",
    "observe",
    "ui_candidates_for",
    "wants_ui_candidates",
    "ElementResolver",
    "ElementHit",
    "resolve_element",
    "PRIMITIVES",
    "ensure_primitives",
    "validate_args",
    "PlanValidation",
    "validate_plan",
    "grounded_plan",
    "validate_or_reject",
    "FAILURE_CATEGORIES",
    "Diagnosis",
    "RecoveryDecision",
    "decide_recovery",
]
