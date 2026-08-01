"""V4.7 Context + Natural Language Understanding.

Reuses ContextEngine + ReferenceResolver + nlu.py.
Does not create a second AgentLoop or switch default voice to HierarchicalPlanner.
"""

from __future__ import annotations

from neuron.v4.context.types import (
    ClarificationState,
    ConfirmationState,
    ContinuityKind,
    ConversationState,
    EntityReference,
    FreshnessKind,
    FRESHNESS_TTL,
    GoalCandidate,
    GoalUpdate,
    IntentFamily,
    ParsedUtterance,
    ResultSet,
    ResultSetItem,
    RouteDest,
    TaskContext,
    Turn,
    UnderstandingResult,
)
from neuron.v4.context.engine import (
    ConversationEngine,
    get_conversation_engine,
    reset_conversation_engine,
)
from neuron.v4.context.bridge import (
    understand_for_agent,
    on_opavr_verified,
    on_ask_user_clarify,
    on_recovery_decision,
    routing_parity_check,
    cancel_for_stop,
)
from neuron.v4.context.normalize import normalize_utterance
from neuron.v4.context.parse import classify_family, parse_ordinal, build_goal

__all__ = [
    "ClarificationState",
    "ConfirmationState",
    "ContinuityKind",
    "ConversationState",
    "ConversationEngine",
    "EntityReference",
    "FreshnessKind",
    "FRESHNESS_TTL",
    "GoalCandidate",
    "GoalUpdate",
    "IntentFamily",
    "ParsedUtterance",
    "ResultSet",
    "ResultSetItem",
    "RouteDest",
    "TaskContext",
    "Turn",
    "UnderstandingResult",
    "get_conversation_engine",
    "reset_conversation_engine",
    "understand_for_agent",
    "on_opavr_verified",
    "on_ask_user_clarify",
    "on_recovery_decision",
    "routing_parity_check",
    "cancel_for_stop",
    "normalize_utterance",
    "classify_family",
    "parse_ordinal",
    "build_goal",
]
