"""V4.4 hierarchical planning types — Goal / TaskPlan / Subgoal / GroundedAction."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    WAITING_FOR_OBSERVATION = "WAITING_FOR_OBSERVATION"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    UNCERTAIN = "UNCERTAIN"


class DecisionKind(str, Enum):
    ACT = "ACT"
    SKIP = "SKIP"
    OBSERVE = "OBSERVE"
    RESOLVE = "RESOLVE"
    CLARIFY = "CLARIFY"
    CONFIRM = "CONFIRM"
    REPLAN = "REPLAN"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"
    CANCELLED = "CANCELLED"
    WAIT = "WAIT"


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Goal:
    text: str = ""
    goal_id: str = ""
    normalized: str = ""
    constraints: list[str] = field(default_factory=list)
    target_applications: list[str] = field(default_factory=list)
    target_monitor: str | int | None = None
    completion_criteria: list[str] = field(default_factory=list)
    safety_context: str = ""
    source: str = "voice"
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.goal_id:
            self.goal_id = _id("goal")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Subgoal:
    description: str = ""
    subgoal_id: str = ""
    intent: str = ""  # open_app | move_monitor | search | play | fullscreen | click | …
    preconditions: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    preferred_tools: list[str] = field(default_factory=list)
    target_hints: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # subgoal_ids
    status: StepStatus = StepStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    last_error: str = ""
    grounded: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subgoal_id:
            self.subgoal_id = _id("sg")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ActionIntent:
    """Unresolved planner intent — must be grounded before execution."""

    kind: str = ""  # tool name or resolve|clarify|observe
    args: dict[str, Any] = field(default_factory=dict)
    reference: str = ""  # for semantic resolve
    target: str = ""
    expected_result: str = ""
    subgoal_id: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroundedAction:
    """Executable tool call — only known tools, validated args."""

    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    target: str = ""
    expected_result: str = ""
    element_id: str = ""
    confidence: float = 0.0
    risk: str = "safe"
    subgoal_id: str = ""
    reason: str = ""
    capability_id: str = ""
    from_intent: ActionIntent | None = None

    def to_legacy_step(self) -> dict[str, Any]:
        step: dict[str, Any] = {
            "action": self.tool,
            "args": dict(self.arguments),
            "target": self.target,
            "expected_result": self.expected_result,
        }
        if self.element_id:
            step["args"] = {**step["args"], "element_id": self.element_id}
        if self.subgoal_id:
            step["subgoal_id"] = self.subgoal_id
        if self.capability_id:
            step["capability_id"] = self.capability_id
        return step

    def to_dict(self) -> dict[str, Any]:
        d = {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "target": self.target,
            "expected_result": self.expected_result,
            "element_id": self.element_id,
            "confidence": self.confidence,
            "risk": self.risk,
            "subgoal_id": self.subgoal_id,
            "reason": self.reason,
            "capability_id": self.capability_id,
        }
        if self.from_intent:
            d["from_intent"] = self.from_intent.to_dict()
        return d


@dataclass
class PlanningDecision:
    kind: DecisionKind = DecisionKind.WAIT
    plan_id: str = ""
    goal_id: str = ""
    subgoal_id: str = ""
    subgoal_description: str = ""
    intent: ActionIntent | None = None
    grounded: GroundedAction | None = None
    clarify_prompt: str = ""
    reason: str = ""
    confidence: float = 0.0
    needs_observation: bool = False
    needs_confirmation: bool = False
    latency_ms: float = 0.0
    revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "subgoal_id": self.subgoal_id,
            "subgoal_description": self.subgoal_description,
            "intent": self.intent.to_dict() if self.intent else None,
            "grounded": self.grounded.to_dict() if self.grounded else None,
            "clarify_prompt": self.clarify_prompt,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "needs_observation": self.needs_observation,
            "needs_confirmation": self.needs_confirmation,
            "latency_ms": round(self.latency_ms, 2),
            "revision": self.revision,
        }


@dataclass
class TaskPlan:
    goal: Goal = field(default_factory=Goal)
    plan_id: str = ""
    subgoals: list[Subgoal] = field(default_factory=list)
    current_subgoal_id: str = ""
    status: PlanStatus = PlanStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    revision: int = 0
    source: str = ""  # template | multi_app | llm | hybrid
    max_subgoals: int = 16
    max_revisions: int = 6
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            self.plan_id = _id("plan")

    def current_subgoal(self) -> Subgoal | None:
        if self.current_subgoal_id:
            for sg in self.subgoals:
                if sg.subgoal_id == self.current_subgoal_id:
                    return sg
        for sg in self.subgoals:
            if sg.status in (StepStatus.PENDING, StepStatus.READY, StepStatus.RUNNING, StepStatus.UNCERTAIN):
                return sg
        return None

    def completed_subgoals(self) -> list[Subgoal]:
        return [s for s in self.subgoals if s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)]

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_legacy_plan(self) -> dict[str, Any]:
        """Flatten remaining ready tools into AgentLoop-compatible steps (best-effort)."""
        steps = []
        for sg in self.subgoals:
            if sg.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED):
                continue
            tool = (sg.preferred_tools[0] if sg.preferred_tools else "") or ""
            if not tool or tool in ("resolve", "observe", "clarify"):
                continue
            steps.append({
                "action": tool,
                "args": dict(sg.target_hints),
                "target": sg.description,
                "expected_result": (sg.completion_criteria[0] if sg.completion_criteria else ""),
                "subgoal_id": sg.subgoal_id,
            })
        return {
            "say": self.goal.text[:120],
            "steps": steps,
            "source": f"v4_plan:{self.source}",
            "plan_id": self.plan_id,
            "goal_id": self.goal.goal_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal.to_dict(),
            "subgoals": [s.to_dict() for s in self.subgoals],
            "current_subgoal_id": self.current_subgoal_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "source": self.source,
            "meta": dict(self.meta),
        }
