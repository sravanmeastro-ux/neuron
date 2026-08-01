"""V4.10 Hierarchical Voice Canary + LIVE Migration boundary.

Integrates V4 Context/Planner/Capability/Safety/Verify/Recover into the real
voice path behind LEGACY/SHADOW/CANARY/HIERARCHICAL modes.

Default: LEGACY. Master flag hierarchical_voice_enabled default false.
Does NOT create a second AgentLoop.
"""

from __future__ import annotations

from neuron.v4.voice.types import (
    VoiceRoutingMode,
    RouteKind,
    TaskOutcomeKind,
    VoiceRequest,
    RouteDecision,
    MigrationReadinessReport,
    voice_metrics,
    reset_voice_metrics,
    VOICE_SHADOW_MISMATCH_COUNT,
    SHADOW_MUTATION_COUNT,
    VOICE_SAFETY_MISMATCH_COUNT,
    VOICE_DUPLICATE_EXECUTION_COUNT,
    UNVERIFIED_COMPLETION_RESPONSE_COUNT,
)
from neuron.v4.voice.config import (
    hierarchical_voice_enabled,
    voice_routing_mode,
    voice_config_snapshot,
    procedure_learning_off,
)
from neuron.v4.voice.canary import (
    CANARY_ALLOW_INTENTS,
    canary_eligible,
    canary_policy_snapshot,
    infer_intent_family,
)
from neuron.v4.voice.shadow import compare_shadow, plan_hierarchical_readonly, is_mutating_tool
from neuron.v4.voice.router import (
    decide_route,
    maybe_handle_voice,
    last_shadow_comparison,
    last_route_decision,
)
from neuron.v4.voice.response import outcome_from_loop, guard_hierarchical_say
from neuron.v4.voice.commit import may_fallback_to_legacy, is_committed
from neuron.v4.voice.report import build_migration_report, write_migration_report


__all__ = [
    "VoiceRoutingMode",
    "RouteKind",
    "TaskOutcomeKind",
    "VoiceRequest",
    "RouteDecision",
    "MigrationReadinessReport",
    "voice_metrics",
    "reset_voice_metrics",
    "VOICE_SHADOW_MISMATCH_COUNT",
    "SHADOW_MUTATION_COUNT",
    "VOICE_SAFETY_MISMATCH_COUNT",
    "VOICE_DUPLICATE_EXECUTION_COUNT",
    "UNVERIFIED_COMPLETION_RESPONSE_COUNT",
    "hierarchical_voice_enabled",
    "voice_routing_mode",
    "voice_config_snapshot",
    "procedure_learning_off",
    "CANARY_ALLOW_INTENTS",
    "canary_eligible",
    "canary_policy_snapshot",
    "infer_intent_family",
    "compare_shadow",
    "plan_hierarchical_readonly",
    "is_mutating_tool",
    "decide_route",
    "maybe_handle_voice",
    "last_shadow_comparison",
    "last_route_decision",
    "outcome_from_loop",
    "guard_hierarchical_say",
    "may_fallback_to_legacy",
    "is_committed",
    "build_migration_report",
    "write_migration_report",
]
