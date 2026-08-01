"""Planner-facing procedure match + TaskPlan expansion helpers.

Does not create a second AgentLoop. Procedures expand to steps executed
via existing run_procedure / AgentLoop path.
"""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.learn.registry import get_procedure_registry
from neuron.v4.learn.preferences import get_preference_store
from neuron.v4.learn.types import ProcedureDefinition


def match_procedure_for_goal(goal_text: str) -> ProcedureDefinition | None:
    """Match enabled learned procedure by aliases/intent — not string-only."""
    reg = get_procedure_registry()
    return reg.match(goal_text or "")


def extract_procedure_params(
    goal_text: str,
    proc: ProcedureDefinition,
    *,
    context_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Instantiate parameters from goal text + ConversationState-like context."""
    params: dict[str, Any] = dict(context_params or {})
    g = goal_text or ""
    names = {p.name for p in proc.parameters}

    if "query" in names and "query" not in params:
        q = None
        # "... on monitor N for QUERY"
        m = re.search(r"(?i)\bon\s+monitor\s*\d+\s+for\s+(.+)$", g)
        if m:
            q = m.group(1).strip(" .")
        if not q:
            # "Do that again for QUERY"
            m2 = re.search(r"(?i)\b(?:again|instead)\s+for\s+(.+)$", g)
            if m2:
                q = m2.group(1).strip(" .")
        if not q:
            # "search|for QUERY" but stop before "on monitor"
            m3 = re.search(
                r"(?i)\b(?:search(?:\s+for)?|query)\s+(.+?)(?:\s+on\s+monitor\b|\s*$)",
                g,
            )
            if m3:
                cand = m3.group(1).strip(" .")
                # Reject if capture is just "on monitor…" noise
                if cand and not re.match(r"(?i)^on\s+monitor\b", cand):
                    q = cand
        if not q:
            m4 = re.search(r"(?i)\bfor\s+(.+?)(?:\s+on\s+monitor\b|\s*$)", g)
            if m4:
                cand = m4.group(1).strip(" .")
                if cand and not re.match(r"(?i)^on\s+monitor\b", cand):
                    q = cand
        if q:
            # Strip trailing "tutorials" noise only if whole phrase kept
            params["query"] = q

    if "monitor" in names:
        task_mon = None
        m = re.search(r"(?i)\bmonitor\s*(\d+)\b", g)
        if m:
            task_mon = int(m.group(1))
        prefs = get_preference_store()
        val, _src = prefs.resolve(
            "monitor",
            task_value=str(task_mon) if task_mon is not None else None,
            procedure_id=proc.procedure_id,
            domain="youtube" if "youtube" in (proc.intent_family or "") else "",
            default=None,
        )
        if val is not None:
            try:
                params["monitor"] = int(val)
            except Exception:
                params["monitor"] = val

    if "app" in names or "browser" in names:
        task_app = None
        for name in ("chrome", "edge", "firefox", "brave"):
            if re.search(rf"\b{name}\b", g, re.I):
                task_app = "Edge" if name == "edge" else name.title()
                break
        prefs = get_preference_store()
        val, _src = prefs.resolve(
            "browser",
            task_value=task_app,
            procedure_id=proc.procedure_id,
            domain="browser",
            default=None,
        )
        if val:
            params["app" if "app" in names else "browser"] = val

    if "result_index" in names and "result_index" not in params:
        m = re.search(r"(?i)\b(first|second|third|\d+)(?:\s+result)?\b", g)
        if m:
            raw = m.group(1).lower()
            ord_map = {"first": 1, "second": 2, "third": 3}
            params["result_index"] = ord_map.get(raw, int(raw) if raw.isdigit() else 1)

    return params


def expand_procedure_plan(
    proc: ProcedureDefinition,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build AgentLoop-compatible plan dict (not direct macro executor)."""
    reg = get_procedure_registry()
    steps = reg.expand(proc.procedure_id, params)
    return {
        "say": f"Running learned procedure {proc.procedure_id}.",
        "steps": steps,
        "procedure_id": proc.procedure_id,
        "version": proc.version,
        "source": "v4_procedure",
    }


def plan_via_procedure(
    goal_text: str,
    *,
    context_params: dict | None = None,
) -> dict[str, Any] | None:
    proc = match_procedure_for_goal(goal_text)
    if not proc:
        return None
    # Do not replace strong built-in atomic youtube.search for trivial one-liners
    g = (goal_text or "").lower()
    if (
        proc.intent_family.startswith("youtube")
        and "monitor" not in g
        and "again" not in g
        and "my youtube" not in g
        and "workflow" not in g
        and proc.confidence < 0.6
    ):
        return None
    params = extract_procedure_params(goal_text, proc, context_params=context_params)
    return expand_procedure_plan(proc, params)


__all__ = [
    "match_procedure_for_goal",
    "extract_procedure_params",
    "expand_procedure_plan",
    "plan_via_procedure",
]
