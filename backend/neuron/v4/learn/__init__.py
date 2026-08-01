"""V4.9 Procedure Learning + Personalization.

Learn reusable COMPOSITE workflows from VERIFIED SUCCESS only.
Execution always: Goal → Planner → Capabilities → Safety → AgentLoop → Verify → Recover.
"""

from __future__ import annotations

from neuron.v4.learn.types import (
    Preference,
    PreferenceScope,
    ProcedureCandidate,
    ProcedureDefinition,
    ProcedureParameter,
    ProcedureSource,
    ProcedureStep,
    TraceStep,
    VerifiedTaskTrace,
    MIN_EVIDENCE_FOR_AUTO_ACCEPT,
    MIN_STEPS_FOR_PROCEDURE,
)
from neuron.v4.learn.eligibility import is_eligible, build_trace
from neuron.v4.learn.privacy import (
    PROCEDURE_PRIVACY_VIOLATION_COUNT,
    validate_privacy,
    privacy_metrics,
    reset_privacy_metrics,
)
from neuron.v4.learn.generalize import generalize_traces
from neuron.v4.learn.learner import (
    ProcedureLearner,
    PROCEDURE_DUPLICATE_COUNT,
    get_procedure_learner,
    reset_procedure_learner,
    reset_duplicate_metrics,
)
from neuron.v4.learn.registry import (
    ProcedureRegistry,
    get_procedure_registry,
    reset_procedure_registry,
)
from neuron.v4.learn.preferences import (
    PreferenceStore,
    get_preference_store,
    reset_preference_store,
)
from neuron.v4.learn.config import procedure_learning_enabled, learning_config
from neuron.v4.learn.hooks import maybe_learn_from_trace, learn_metrics


__all__ = [
    "Preference",
    "PreferenceScope",
    "ProcedureCandidate",
    "ProcedureDefinition",
    "ProcedureParameter",
    "ProcedureSource",
    "ProcedureStep",
    "TraceStep",
    "VerifiedTaskTrace",
    "MIN_EVIDENCE_FOR_AUTO_ACCEPT",
    "MIN_STEPS_FOR_PROCEDURE",
    "is_eligible",
    "build_trace",
    "validate_privacy",
    "privacy_metrics",
    "reset_privacy_metrics",
    "PROCEDURE_PRIVACY_VIOLATION_COUNT",
    "generalize_traces",
    "ProcedureLearner",
    "PROCEDURE_DUPLICATE_COUNT",
    "get_procedure_learner",
    "reset_procedure_learner",
    "reset_duplicate_metrics",
    "ProcedureRegistry",
    "get_procedure_registry",
    "reset_procedure_registry",
    "PreferenceStore",
    "get_preference_store",
    "reset_preference_store",
    "procedure_learning_enabled",
    "learning_config",
    "maybe_learn_from_trace",
    "learn_metrics",
]
