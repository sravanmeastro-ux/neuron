"""V4.7 conversational context + NLU types.

Ownership:
  DesktopWorldModel  — observable desktop
  ConversationState  — linguistic/task continuity (this module)
  TaskPlan           — goal/subgoal execution
  Persistent memory  — durable prefs only (existing policy)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class IntentFamily(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    FOCUS = "FOCUS"
    MOVE = "MOVE"
    SEARCH = "SEARCH"
    NAVIGATE = "NAVIGATE"
    PLAY = "PLAY"
    PAUSE = "PAUSE"
    CLICK = "CLICK"
    TYPE = "TYPE"
    SELECT = "SELECT"
    SCROLL = "SCROLL"
    VOLUME = "VOLUME"
    FILE = "FILE"
    APP_ACTION = "APP_ACTION"
    MULTI_STEP_GOAL = "MULTI_STEP_GOAL"
    FOLLOW_UP = "FOLLOW_UP"
    CORRECTION = "CORRECTION"
    CANCEL = "CANCEL"
    CONFIRMATION = "CONFIRMATION"
    CLARIFICATION_RESPONSE = "CLARIFICATION_RESPONSE"
    FULLSCREEN = "FULLSCREEN"
    STOP = "STOP"
    UNKNOWN = "UNKNOWN"


class ContinuityKind(str, Enum):
    NEW_GOAL = "NEW_GOAL"
    FOLLOW_UP = "FOLLOW_UP"
    CORRECTION = "CORRECTION"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"
    CONFIRMATION_ANSWER = "CONFIRMATION_ANSWER"
    CANCEL = "CANCEL"
    ELLIPSIS = "ELLIPSIS"


class RouteDest(str, Enum):
    FAST_PATH = "FAST_PATH"
    HIERARCHICAL = "HIERARCHICAL"
    CLARIFY = "CLARIFY"
    CONFIRM = "CONFIRM"
    STOP = "STOP"
    REJECT = "REJECT"


class FreshnessKind(str, Enum):
    ELEMENT = "ELEMENT"
    RESULT_SET = "RESULT_SET"
    APP = "APP"
    MONITOR = "MONITOR"
    TASK = "TASK"
    CLARIFY = "CLARIFY"
    CONFIRM = "CONFIRM"


FRESHNESS_TTL: dict[str, float] = {
    FreshnessKind.ELEMENT.value: 45.0,
    FreshnessKind.RESULT_SET.value: 120.0,
    FreshnessKind.APP.value: 600.0,
    FreshnessKind.MONITOR.value: 600.0,
    FreshnessKind.TASK.value: 900.0,
    FreshnessKind.CLARIFY.value: 120.0,
    FreshnessKind.CONFIRM.value: 90.0,
}


@dataclass
class EntityReference:
    entity_type: str = ""
    value: str = ""
    normalized: str = ""
    source_turn: str = ""
    confidence: float = 0.5
    world_ref: str = ""
    verified: bool = False
    uncertain: bool = False
    at: float = field(default_factory=time.time)

    def is_fresh(self, now: float | None = None, ttl: float | None = None) -> bool:
        now = now if now is not None else time.time()
        if ttl is None:
            if self.entity_type == "app":
                ttl = FRESHNESS_TTL[FreshnessKind.APP.value]
            elif self.entity_type == "monitor":
                ttl = FRESHNESS_TTL[FreshnessKind.MONITOR.value]
            else:
                ttl = FRESHNESS_TTL[FreshnessKind.ELEMENT.value]
        return (now - self.at) <= ttl

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "value": self.value[:80],
            "normalized": self.normalized[:80],
            "source_turn": self.source_turn,
            "confidence": round(self.confidence, 3),
            "world_ref": self.world_ref[:64],
            "verified": self.verified,
            "uncertain": self.uncertain,
            "at": self.at,
        }


@dataclass
class ResultSetItem:
    index: int
    label: str = ""
    world_ref: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultSet:
    result_id: str = ""
    source: str = ""
    application: str = ""
    window_ref: str = ""
    query: str = ""
    items: list[ResultSetItem] = field(default_factory=list)
    at: float = field(default_factory=time.time)
    stale: bool = False

    def __post_init__(self) -> None:
        if not self.result_id:
            self.result_id = _id("rs")

    def is_fresh(self, now: float | None = None) -> bool:
        if self.stale:
            return False
        now = now if now is not None else time.time()
        return (now - self.at) <= FRESHNESS_TTL[FreshnessKind.RESULT_SET.value]

    def pick(self, ordinal: int) -> ResultSetItem | None:
        if not self.items or not self.is_fresh():
            return None
        if ordinal < 0:
            idx = len(self.items) + ordinal
        else:
            idx = ordinal - 1
        if 0 <= idx < len(self.items):
            return self.items[idx]
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "source": self.source,
            "application": self.application,
            "query": self.query[:120],
            "n_items": len(self.items),
            "stale": self.stale,
            "fresh": self.is_fresh(),
            "at": self.at,
        }


@dataclass
class ClarificationState:
    clarification_id: str = ""
    prompt: str = ""
    original_goal: str = ""
    original_action: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    expected_answer_type: str = "choice"
    safety_context: str = ""
    source: str = ""
    plan_id: str = ""
    subgoal_id: str = ""
    at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.clarification_id:
            self.clarification_id = _id("clr")
        if not self.expires_at:
            self.expires_at = self.at + FRESHNESS_TTL[FreshnessKind.CLARIFY.value]

    def is_active(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return now <= self.expires_at and bool(self.prompt or self.options)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarification_id": self.clarification_id,
            "prompt": self.prompt[:200],
            "original_goal": self.original_goal[:120],
            "n_options": len(self.options),
            "expected_answer_type": self.expected_answer_type,
            "source": self.source,
            "active": self.is_active(),
            "expires_at": self.expires_at,
        }


@dataclass
class ConfirmationState:
    confirmation_id: str = ""
    action: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    target: str = ""
    risk: str = ""
    task: str = ""
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.confirmation_id:
            self.confirmation_id = _id("cfm")
        if not self.expires_at:
            self.expires_at = self.at + FRESHNESS_TTL[FreshnessKind.CONFIRM.value]

    def is_active(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return now <= self.expires_at and bool(self.action or self.plan_steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "action": self.action,
            "target": self.target[:80],
            "risk": self.risk,
            "active": self.is_active(),
            "expires_at": self.expires_at,
        }


@dataclass
class TaskContext:
    goal_text: str = ""
    goal_id: str = ""
    plan_id: str = ""
    active_application: str = ""
    active_window: str = ""
    active_monitor: str | int | None = None
    active_browser_url: str = ""
    active_page_hint: str = ""
    last_query: str = ""
    last_media_ref: str = ""
    media_fullscreen: str = "unknown"
    verified_facts: dict[str, Any] = field(default_factory=dict)
    uncertain_facts: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)

    def is_fresh(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return (now - self.at) <= FRESHNESS_TTL[FreshnessKind.TASK.value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_text": self.goal_text[:160],
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "active_application": self.active_application,
            "active_monitor": self.active_monitor,
            "active_browser_url": self.active_browser_url[:120],
            "last_query": self.last_query[:80],
            "media_fullscreen": self.media_fullscreen,
            "verified_facts": {
                k: str(v)[:80] for k, v in list(self.verified_facts.items())[:12]
            },
            "uncertain_facts": list(self.uncertain_facts.keys())[:8],
            "fresh": self.is_fresh(),
        }


@dataclass
class Turn:
    turn_id: str = ""
    raw: str = ""
    normalized: str = ""
    intent_family: IntentFamily = IntentFamily.UNKNOWN
    continuity: ContinuityKind = ContinuityKind.NEW_GOAL
    confidence: float = 0.5
    route: RouteDest = RouteDest.FAST_PATH
    at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.turn_id:
            self.turn_id = _id("turn")

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "normalized": self.normalized[:160],
            "intent_family": self.intent_family.value,
            "continuity": self.continuity.value,
            "confidence": round(self.confidence, 3),
            "route": self.route.value,
            "at": self.at,
        }


@dataclass
class ParsedUtterance:
    raw: str = ""
    cleaned: str = ""
    canonical: str = ""
    variants: list[str] = field(default_factory=list)
    fillers_stripped: bool = False
    negation: bool = False
    negation_target: str = ""
    correction_abandoned: str = ""
    correction_final: str = ""
    compound_parts: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw[:160],
            "canonical": self.canonical[:160],
            "negation": self.negation,
            "negation_target": self.negation_target[:80],
            "correction_abandoned": self.correction_abandoned[:80],
            "correction_final": self.correction_final[:80],
            "compound_parts": [p[:80] for p in self.compound_parts[:6]],
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class GoalCandidate:
    text: str = ""
    normalized: str = ""
    intent_family: IntentFamily = IntentFamily.UNKNOWN
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    multi_step: bool = False
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text[:160],
            "normalized": self.normalized[:160],
            "intent_family": self.intent_family.value,
            "args": {k: str(v)[:80] for k, v in list(self.args.items())[:12]},
            "confidence": round(self.confidence, 3),
            "multi_step": self.multi_step,
            "source": self.source,
        }


@dataclass
class GoalUpdate:
    kind: str = "replace"
    text: str = ""
    args_patch: dict[str, Any] = field(default_factory=dict)
    preserve_verified: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text[:160],
            "args_patch": {k: str(v)[:80] for k, v in list(self.args_patch.items())[:8]},
            "preserve_verified": self.preserve_verified,
            "reason": self.reason[:120],
        }


@dataclass
class UnderstandingResult:
    turn: Turn | None = None
    parsed: ParsedUtterance | None = None
    goal: GoalCandidate | None = None
    goal_update: GoalUpdate | None = None
    continuity: ContinuityKind = ContinuityKind.NEW_GOAL
    route: RouteDest = RouteDest.FAST_PATH
    route_reason: str = ""
    rewritten_command: str = ""
    clarification: ClarificationState | None = None
    clarification_resolution: dict[str, Any] | None = None
    confirmation_resolution: dict[str, Any] | None = None
    resolved_entities: list[EntityReference] = field(default_factory=list)
    confidence: float = 0.5
    latency_ms: float = 0.0
    used_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "continuity": self.continuity.value,
            "route": self.route.value,
            "route_reason": self.route_reason[:160],
            "rewritten_command": self.rewritten_command[:160],
            "confidence": round(self.confidence, 3),
            "latency_ms": round(self.latency_ms, 2),
            "used_llm": self.used_llm,
            "goal": self.goal.to_dict() if self.goal else None,
            "goal_update": self.goal_update.to_dict() if self.goal_update else None,
            "clarification_resolution": self.clarification_resolution,
            "confirmation_resolution": self.confirmation_resolution,
            "n_entities": len(self.resolved_entities),
            "turn": self.turn.to_dict() if self.turn else None,
            "parsed": self.parsed.to_dict() if self.parsed else None,
        }


@dataclass
class ConversationState:
    session_id: str = ""
    turn_id: str = ""
    task: TaskContext = field(default_factory=TaskContext)
    result_set: ResultSet | None = None
    pending_clarification: ClarificationState | None = None
    pending_confirmation: ConfirmationState | None = None
    last_referenced: EntityReference | None = None
    last_resolved_element: EntityReference | None = None
    last_interacted: EntityReference | None = None
    recent_entities: list[EntityReference] = field(default_factory=list)
    recent_turns: list[Turn] = field(default_factory=list)
    last_successful_action: str = ""
    last_verified_summary: str = ""
    at: float = field(default_factory=time.time)

    MAX_TURNS = 12
    MAX_ENTITIES = 24

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = _id("sess")

    def push_turn(self, turn: Turn) -> None:
        self.recent_turns.append(turn)
        if len(self.recent_turns) > self.MAX_TURNS:
            self.recent_turns = self.recent_turns[-self.MAX_TURNS :]
        self.turn_id = turn.turn_id
        self.at = time.time()

    def note_entity(self, ent: EntityReference) -> None:
        self.recent_entities.append(ent)
        if len(self.recent_entities) > self.MAX_ENTITIES:
            self.recent_entities = self.recent_entities[-self.MAX_ENTITIES :]
        self.last_referenced = ent

    def clear_pending_unsafe(self) -> None:
        self.pending_clarification = None
        self.pending_confirmation = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "task": self.task.to_dict(),
            "result_set": self.result_set.to_dict() if self.result_set else None,
            "pending_clarification": (
                self.pending_clarification.to_dict()
                if self.pending_clarification
                else None
            ),
            "pending_confirmation": (
                self.pending_confirmation.to_dict()
                if self.pending_confirmation
                else None
            ),
            "last_referenced": (
                self.last_referenced.to_dict() if self.last_referenced else None
            ),
            "n_turns": len(self.recent_turns),
            "n_entities": len(self.recent_entities),
            "last_successful_action": self.last_successful_action,
            "last_verified_summary": self.last_verified_summary[:120],
        }


__all__ = [
    "IntentFamily",
    "ContinuityKind",
    "RouteDest",
    "FreshnessKind",
    "FRESHNESS_TTL",
    "EntityReference",
    "ResultSetItem",
    "ResultSet",
    "ClarificationState",
    "ConfirmationState",
    "TaskContext",
    "Turn",
    "ParsedUtterance",
    "GoalCandidate",
    "GoalUpdate",
    "UnderstandingResult",
    "ConversationState",
]
