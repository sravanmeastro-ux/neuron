"""V4.8 Domain Skills + Tool Integration.

CapabilityCatalog indexes ToolRegistry; HierarchicalPlanner resolves WHAT→HOW.
CapabilityRouter remains for fast path; default voice is NOT switched.
"""

from __future__ import annotations

from neuron.v4.capability.types import (
    CapabilityDescriptor,
    CapabilityDomain,
    CapabilityKind,
    CapabilityResolution,
    CapabilityStats,
    FailureMemory,
)
from neuron.v4.capability.catalog import (
    CapabilityCatalog,
    get_capability_catalog,
    reset_capability_catalog,
)
from neuron.v4.capability.resolve import resolve_intent, resolve_action_intent
from neuron.v4.capability.confirm_resume import (
    request_confirm_scoped,
    resume_confirmation_via_agent_loop,
    cancel_confirmation,
    peek_pending,
    invalidate_if_stale,
)
from neuron.v4.capability.bridge import (
    shared_semantic_tool,
    suggest_recovery_alternates,
    coverage_report,
    router_capability_to_canonical,
)
from neuron.v4.capability.expectations import verification_for, preconditions_for

__all__ = [
    "CapabilityDescriptor",
    "CapabilityDomain",
    "CapabilityKind",
    "CapabilityResolution",
    "CapabilityStats",
    "FailureMemory",
    "CapabilityCatalog",
    "get_capability_catalog",
    "reset_capability_catalog",
    "resolve_intent",
    "resolve_action_intent",
    "request_confirm_scoped",
    "resume_confirmation_via_agent_loop",
    "cancel_confirmation",
    "peek_pending",
    "invalidate_if_stale",
    "shared_semantic_tool",
    "suggest_recovery_alternates",
    "coverage_report",
    "router_capability_to_canonical",
    "verification_for",
    "preconditions_for",
]
