"""V4 typed state objects.

These are the canonical shapes for the upgraded AgentLoop lifecycle.
They wrap / extend existing V3 structures without requiring a second loop.

Mapping to existing code:
  Goal / Task     ↔ neuron.brain.goal.GoalState (goal text + status)
  Plan / PlanStep ↔ plan dict {"steps":[{"action","args",...}]}
  Observation     ↔ verifier.observe_world / ComputerState / v3.Observation
  VerificationResult ↔ VerifyResult + SUCCESS|FAILURE|UNCERTAIN
  RecoveryDecision ↔ neuron.v3.loop_types.RecoveryDecision
  AgentState      ↔ GoalState + ContextEngine + WorldState (unified view)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationOutcome(str, Enum):
    """Never coerce UNCERTAIN → SUCCESS."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNCERTAIN = "UNCERTAIN"


class AgentPhase(str, Enum):
    """Lifecycle phases for observability / HUD (V4)."""

    RECEIVE_GOAL = "RECEIVE_GOAL"
    UNDERSTAND = "UNDERSTAND"
    OBSERVE = "OBSERVE"
    GROUND = "GROUND"
    PLAN = "PLAN"
    SELECT_ACTION = "SELECT_ACTION"
    SAFETY_CHECK = "SAFETY_CHECK"
    ACT = "ACT"
    WAIT_FOR_EFFECT = "WAIT_FOR_EFFECT"
    OBSERVE_AGAIN = "OBSERVE_AGAIN"
    VERIFY = "VERIFY"
    RECOVER_OR_CONTINUE = "RECOVER_OR_CONTINUE"
    COMPLETE = "COMPLETE"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


@dataclass
class Goal:
    """Original user goal (natural language)."""

    text: str = ""
    task_id: str = ""
    source: str = "voice"  # voice | text | bench
    created_at: float = 0.0


@dataclass
class Task:
    """Current subgoal within a Goal."""

    text: str = ""
    parent_goal: str = ""
    status: str = "pending"  # pending | running | success | failed | cancelled
    index: int = 0


@dataclass
class PlanStep:
    """One executable tool step — must go through ToolRegistry."""

    action: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    expected_result: str = ""
    say: str = ""
    timeout: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_legacy(self) -> dict[str, Any]:
        out: dict[str, Any] = {"action": self.action, "args": dict(self.args)}
        if self.expected_result:
            out["expected_result"] = self.expected_result
        if self.say:
            out["say"] = self.say
        if self.timeout is not None:
            out["timeout"] = self.timeout
        if self.meta:
            out["meta"] = dict(self.meta)
        return out

    @classmethod
    def from_legacy(cls, step: dict[str, Any] | None) -> "PlanStep":
        step = step or {}
        return cls(
            action=str(step.get("action") or ""),
            args=dict(step.get("args") or {}),
            expected_result=str(step.get("expected_result") or ""),
            say=str(step.get("say") or ""),
            timeout=step.get("timeout"),
            meta=dict(step.get("meta") or {}),
        )


@dataclass
class Plan:
    """Structured plan — never free-form LLM prose for execution."""

    steps: list[PlanStep] = field(default_factory=list)
    say: str = ""
    source: str = ""  # capability | grounded_llm | multi_app | procedure | hierarchical
    meta: dict[str, Any] = field(default_factory=dict)

    def to_legacy(self) -> dict[str, Any]:
        return {
            "say": self.say,
            "steps": [s.to_legacy() for s in self.steps],
            "source": self.source,
            **({"meta": dict(self.meta)} if self.meta else {}),
        }

    @classmethod
    def from_legacy(cls, plan: dict[str, Any] | None) -> "Plan":
        plan = plan or {}
        steps = [PlanStep.from_legacy(s) for s in (plan.get("steps") or [])]
        return cls(
            steps=steps,
            say=str(plan.get("say") or ""),
            source=str(plan.get("source") or plan.get("via") or ""),
            meta=dict(plan.get("meta") or {}),
        )


@dataclass
class Observation:
    """Structured desktop observation (V4 view; world model fills this later)."""

    desktop: dict[str, Any] = field(default_factory=dict)
    active_window: dict[str, Any] = field(default_factory=dict)
    monitors: list[dict[str, Any]] = field(default_factory=list)
    visible_elements: list[dict[str, Any]] = field(default_factory=list)
    ocr_text: list[str] = field(default_factory=list)
    application_hints: list[str] = field(default_factory=list)
    changes_since_previous: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    fingerprint: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    captured_at: float = 0.0


@dataclass
class Action:
    """Selected tool invocation after safety check."""

    name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    risk: str = "safe"
    step_index: int = 0


@dataclass
class ActionResult:
    """Raw tool outcome — not task success by itself."""

    ok: bool = False
    message: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    needs_confirm: bool = False
    error: str = ""
    latency_ms: float = 0.0


@dataclass
class VerificationResult:
    """Postcondition check. UNCERTAIN must not become SUCCESS."""

    outcome: VerificationOutcome = VerificationOutcome.UNCERTAIN
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    category: str = ""  # failure category when FAILURE

    @property
    def success(self) -> bool:
        return self.outcome is VerificationOutcome.SUCCESS

    @classmethod
    def from_bool(
        cls,
        ok: bool | None,
        *,
        detail: str = "",
        uncertain_when_none: bool = True,
        category: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> "VerificationResult":
        if ok is True:
            outcome = VerificationOutcome.SUCCESS
        elif ok is False:
            outcome = VerificationOutcome.FAILURE
        elif uncertain_when_none:
            outcome = VerificationOutcome.UNCERTAIN
        else:
            outcome = VerificationOutcome.FAILURE
        return cls(
            outcome=outcome,
            detail=detail,
            category=category,
            evidence=dict(evidence or {}),
        )


@dataclass
class RecoveryDecision:
    """Bounded recovery choice (compatible with v3.loop_types)."""

    strategy: str = "none"  # retry | alternate | replan | ask_user | blocked | none
    reason: str = ""
    alternate_action: str = ""
    alternate_args: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0

    @classmethod
    def from_v3(cls, decision: Any) -> "RecoveryDecision":
        if decision is None:
            return cls()
        if isinstance(decision, dict):
            return cls(
                strategy=str(decision.get("strategy") or decision.get("action") or "none"),
                reason=str(decision.get("reason") or ""),
                alternate_action=str(decision.get("alternate_action") or ""),
                alternate_args=dict(decision.get("alternate_args") or {}),
                max_retries=int(decision.get("max_retries") or 0),
            )
        return cls(
            strategy=str(getattr(decision, "strategy", None) or getattr(decision, "action", None) or "none"),
            reason=str(getattr(decision, "reason", "") or ""),
            alternate_action=str(getattr(decision, "alternate_action", "") or ""),
            alternate_args=dict(getattr(decision, "alternate_args", None) or {}),
            max_retries=int(getattr(decision, "max_retries", 0) or 0),
        )


@dataclass
class AgentState:
    """Unified loop state — what the AgentLoop must know."""

    goal: Goal = field(default_factory=Goal)
    current_subgoal: Task = field(default_factory=Task)
    plan: Plan = field(default_factory=Plan)
    completed_steps: list[PlanStep] = field(default_factory=list)
    phase: AgentPhase = AgentPhase.RECEIVE_GOAL

    # Desktop (filled by world model / observation)
    desktop: dict[str, Any] = field(default_factory=dict)
    focused_application: str = ""
    focused_window: str = ""
    active_monitor: int | None = None
    known_windows: list[dict[str, Any]] = field(default_factory=list)
    visible_elements: list[dict[str, Any]] = field(default_factory=list)
    # V4.1 snapshot handles (dicts; full typed state via get_world_model())
    world_before: dict[str, Any] | None = None
    world_after: dict[str, Any] | None = None
    world_diff: dict[str, Any] | None = None

    last_observation: Observation | None = None
    previous_actions: list[Action] = field(default_factory=list)
    last_action_result: ActionResult | None = None
    last_verification: VerificationResult | None = None
    last_recovery: RecoveryDecision | None = None

    retries: int = 0
    errors: list[str] = field(default_factory=list)
    safety_state: str = "clear"  # clear | needs_confirm | blocked
    interrupted: bool = False
    status: str = "running"  # running | success | failed | needs_confirm | interrupted

    def apply_desktop_snapshot(self, state: Any, *, which: str = "current") -> None:
        """Copy queryable fields from a DesktopState into AgentState."""
        if state is None:
            return
        try:
            fw = getattr(state, "foreground_window", None)
            app = getattr(state, "foreground_application", None)
            self.focused_application = (
                (app.name if app else "")
                or (fw.application if fw else "")
                or self.focused_application
            )
            self.focused_window = (fw.title if fw else "") or self.focused_window
            self.active_monitor = getattr(state, "active_monitor_id", None)
            self.known_windows = [w.to_dict() for w in (getattr(state, "windows", None) or [])]
            self.visible_elements = [
                e.to_dict() for e in (getattr(state, "visible_elements", None) or [])
            ]
            snap = state.to_dict() if hasattr(state, "to_dict") else {}
            self.desktop = snap
            if which == "before":
                self.world_before = snap
            elif which == "after":
                self.world_after = snap
        except Exception:
            pass

    def mark_interrupted(self) -> None:
        self.interrupted = True
        self.phase = AgentPhase.INTERRUPTED
        self.status = "interrupted"
