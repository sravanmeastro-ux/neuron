"""Task Planning Engine types — goals, subtasks, graphs, execution state."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class GoalSpec:
    text: str = ""
    goal_id: str = ""
    summary: str = ""
    applications: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    destructive: bool = False
    source: str = "voice"
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.goal_id:
            self.goal_id = _id("goal")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Subtask:
    """One node in the dependency graph."""

    description: str = ""
    subtask_id: str = ""
    action: str = ""  # tool name
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    expected_result: str = ""
    target: str = ""
    status: StepStatus = StepStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    last_error: str = ""
    last_signature: str = ""  # avoid repeating identical failures
    requires_confirm: bool = False
    use_screen: bool = False  # prefer Screen Understanding for this step
    use_fast: bool = False  # eligible for FastIntentRouter single-step

    def __post_init__(self) -> None:
        if not self.subtask_id:
            self.subtask_id = _id("st")

    def signature(self) -> str:
        return f"{self.action}|{sorted((self.args or {}).items())}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def as_tool_step(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "tool": self.action,
            "args": dict(self.args or {}),
            "arguments": dict(self.args or {}),
            "target": self.target or self.description,
            "expected_result": self.expected_result or self.description,
            "subtask_id": self.subtask_id,
        }


@dataclass
class TaskGraph:
    goal: GoalSpec = field(default_factory=GoalSpec)
    subtasks: list[Subtask] = field(default_factory=list)
    plan_id: str = ""
    source: str = "template"  # template | generic | multi_app | llm
    planner_ms: float = 0.0

    def __post_init__(self) -> None:
        if not self.plan_id:
            self.plan_id = _id("plan")

    def by_id(self) -> dict[str, Subtask]:
        return {s.subtask_id: s for s in self.subtasks}

    def ready(self) -> list[Subtask]:
        done = {
            s.subtask_id
            for s in self.subtasks
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        }
        out: list[Subtask] = []
        for s in self.subtasks:
            if s.status not in (StepStatus.PENDING, StepStatus.READY, StepStatus.FAILED):
                continue
            if s.status == StepStatus.FAILED and s.attempt_count >= s.max_attempts:
                continue
            if all(d in done for d in (s.depends_on or [])):
                out.append(s)
        return out

    def all_done(self) -> bool:
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.subtasks
        )

    def has_failed_terminal(self) -> bool:
        return any(
            s.status == StepStatus.FAILED and s.attempt_count >= s.max_attempts
            for s in self.subtasks
        )

    def to_legacy_plan(self) -> dict[str, Any]:
        """Linearize by dependency order for AgentLoop injection."""
        ordered = topological_order(self.subtasks)
        return {
            "say": self.goal.summary or self.goal.text,
            "steps": [s.as_tool_step() for s in ordered],
            "source": f"taskplan:{self.source}",
            "plan_id": self.plan_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "source": self.source,
            "planner_ms": self.planner_ms,
            "goal": self.goal.to_dict(),
            "subtasks": [s.to_dict() for s in self.subtasks],
        }


def topological_order(subtasks: list[Subtask]) -> list[Subtask]:
    """Kahn topological sort; falls back to original list order on cycles."""
    by = {s.subtask_id: s for s in subtasks}
    indeg = {s.subtask_id: 0 for s in subtasks}
    children: dict[str, list[str]] = {s.subtask_id: [] for s in subtasks}
    for s in subtasks:
        for d in s.depends_on or []:
            if d not in by:
                continue
            indeg[s.subtask_id] += 1
            children[d].append(s.subtask_id)
    queue = [sid for sid, n in indeg.items() if n == 0]
    ordered: list[Subtask] = []
    while queue:
        queue.sort(
            key=lambda sid: next(
                i for i, s in enumerate(subtasks) if s.subtask_id == sid
            )
        )
        sid = queue.pop(0)
        ordered.append(by[sid])
        for c in children[sid]:
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    if len(ordered) != len(subtasks):
        return list(subtasks)
    return ordered


@dataclass
class Observation:
    application: str = ""
    window_title: str = ""
    notes: str = ""
    ts: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionReport:
    goal: str = ""
    status: str = ""
    completion_ms: float = 0.0
    planner_ms: float = 0.0
    execution_ms: float = 0.0
    success: bool = False
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    retry_count: int = 0
    recovery_count: int = 0
    cancelled: bool = False
    needs_confirm: dict[str, Any] | None = None
    say: str = ""
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskState:
    """Mutable execution memory for resume / progress."""

    goal: GoalSpec = field(default_factory=GoalSpec)
    graph: TaskGraph | None = None
    status: TaskStatus = TaskStatus.PENDING
    current_subtask_id: str = ""
    completed_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    pending_ids: list[str] = field(default_factory=list)
    current_application: str = ""
    focused_window: str = ""
    recent_observations: list[Observation] = field(default_factory=list)
    retry_count: int = 0
    recovery_count: int = 0
    planner_ms: float = 0.0
    execution_ms: float = 0.0
    started_at: float = 0.0
    updated_at: float = field(default_factory=time.time)
    last_error: str = ""
    pending_confirm: dict[str, Any] | None = None
    say: str = ""

    def sync_from_graph(self) -> None:
        if not self.graph:
            return
        self.completed_ids = [
            s.subtask_id
            for s in self.graph.subtasks
            if s.status == StepStatus.COMPLETED
        ]
        self.failed_ids = [
            s.subtask_id for s in self.graph.subtasks if s.status == StepStatus.FAILED
        ]
        self.pending_ids = [
            s.subtask_id
            for s in self.graph.subtasks
            if s.status in (StepStatus.PENDING, StepStatus.READY, StepStatus.RUNNING)
        ]
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal.to_dict(),
            "status": self.status.value,
            "current_subtask_id": self.current_subtask_id,
            "completed_ids": list(self.completed_ids),
            "failed_ids": list(self.failed_ids),
            "pending_ids": list(self.pending_ids),
            "current_application": self.current_application,
            "focused_window": self.focused_window,
            "recent_observations": [o.to_dict() for o in self.recent_observations[-8:]],
            "retry_count": self.retry_count,
            "recovery_count": self.recovery_count,
            "planner_ms": self.planner_ms,
            "execution_ms": self.execution_ms,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "pending_confirm": self.pending_confirm,
            "say": self.say,
            "graph": self.graph.to_dict() if self.graph else None,
        }
