"""Plan structure validation — bounds, tools, deps, cycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neuron.v4.plan import tools as plan_tools
from neuron.v4.plan.types import TaskPlan

MAX_SUBGOALS = 16
MAX_ATTEMPTS = 3
MAX_REVISIONS = 6


@dataclass
class PlanValidation:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> "PlanValidation":
        self.ok = False
        self.errors.append(msg)
        return self


def validate_plan(plan: TaskPlan | None) -> PlanValidation:
    v = PlanValidation()
    if plan is None:
        return v.fail("plan is None")
    if len(plan.subgoals) == 0:
        return v.fail("plan has no subgoals")
    if len(plan.subgoals) > MAX_SUBGOALS:
        return v.fail(f"too many subgoals ({len(plan.subgoals)} > {MAX_SUBGOALS})")
    if plan.revision > MAX_REVISIONS:
        return v.fail(f"revision budget exceeded ({plan.revision} > {MAX_REVISIONS})")

    ids = [sg.subgoal_id for sg in plan.subgoals]
    if len(ids) != len(set(ids)):
        v.fail("duplicate subgoal ids")

    id_set = set(ids)
    for sg in plan.subgoals:
        if sg.max_attempts > MAX_ATTEMPTS:
            sg.max_attempts = MAX_ATTEMPTS
        for dep in sg.depends_on:
            if dep not in id_set:
                v.fail(f"subgoal {sg.subgoal_id} depends on unknown {dep}")
        for tool in sg.preferred_tools:
            if tool in ("resolve", "observe", "clarify", "skip", "wait"):
                continue
            if not plan_tools.is_known_tool(tool):
                v.warnings.append(f"tool not registered (may fail grounding): {tool}")

    # Simple cycle detection on depends_on
    if _has_cycle(plan):
        v.fail("subgoal dependency cycle detected")

    return v


def _has_cycle(plan: TaskPlan) -> bool:
    graph = {sg.subgoal_id: list(sg.depends_on) for sg in plan.subgoals}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in graph.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[u] == WHITE and dfs(u) for u in graph)


def validate_llm_plan_dict(raw: Any) -> tuple[bool, str, list[dict]]:
    """Validate LLM planner JSON before converting to TaskPlan."""
    if not isinstance(raw, dict):
        return False, "LLM plan must be a dict", []
    steps = raw.get("steps")
    if not isinstance(steps, list):
        return False, "LLM plan missing steps list", []
    if len(steps) > MAX_SUBGOALS:
        return False, f"LLM plan too large ({len(steps)})", []
    clean: list[dict] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"step {i} not a dict", []
        action = str(step.get("action") or step.get("tool") or "").strip()
        if not action:
            return False, f"step {i} missing action", []
        if action.lower() in ("run_shell", "eval", "exec", "python", "subprocess"):
            return False, f"forbidden tool in LLM plan: {action}", []
        if not plan_tools.is_known_tool(action):
            return False, f"unknown tool in LLM plan: {action}", []
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        ok, err, coerced = plan_tools.validate_tool_call(action, args)
        if not ok:
            return False, f"invalid args for {action}: {err}", []
        clean.append({
            "action": action,
            "args": coerced,
            "target": str(step.get("target") or ""),
            "expected_result": str(step.get("expected_result") or ""),
        })
    return True, "", clean


__all__ = [
    "PlanValidation",
    "validate_plan",
    "validate_llm_plan_dict",
    "MAX_SUBGOALS",
    "MAX_ATTEMPTS",
    "MAX_REVISIONS",
]
