"""Edit workflows — steps, variables, loops, conditions."""

from __future__ import annotations

from typing import Any

from neuron.workflows import store
from neuron.workflows.types import Workflow, WorkflowStep


def list_all() -> list[dict[str, Any]]:
    return [w.summary() for w in store.list_workflows()]


def get_detail(workflow_id: str) -> dict[str, Any] | None:
    w = store.get(workflow_id)
    return w.to_dict() if w else None


def update_meta(
    workflow_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> Workflow | None:
    w = store.get(workflow_id)
    if not w:
        return None
    if name is not None:
        w.name = name
    if description is not None:
        w.description = description
    if tags is not None:
        w.tags = list(tags)
    w.version = int(w.version or 1) + 1
    return store.save(w)


def set_variables(workflow_id: str, variables: dict[str, Any], *, merge: bool = True) -> Workflow | None:
    w = store.get(workflow_id)
    if not w:
        return None
    if merge:
        w.variables.update(variables or {})
    else:
        w.variables = dict(variables or {})
    w.version = int(w.version or 1) + 1
    return store.save(w)


def replace_steps(workflow_id: str, steps: list[dict[str, Any]]) -> Workflow | None:
    w = store.get(workflow_id)
    if not w:
        return None
    w.steps = [WorkflowStep.from_dict(s) for s in steps]
    w.version = int(w.version or 1) + 1
    return store.save(w)


def insert_step(workflow_id: str, index: int, step: dict[str, Any]) -> Workflow | None:
    w = store.get(workflow_id)
    if not w:
        return None
    s = WorkflowStep.from_dict(step)
    idx = max(0, min(int(index), len(w.steps)))
    w.steps.insert(idx, s)
    w.version = int(w.version or 1) + 1
    return store.save(w)


def delete_step(workflow_id: str, index: int) -> Workflow | None:
    w = store.get(workflow_id)
    if not w:
        return None
    if index < 0 or index >= len(w.steps):
        return None
    w.steps.pop(index)
    w.version = int(w.version or 1) + 1
    return store.save(w)


def update_step(workflow_id: str, index: int, step: dict[str, Any]) -> Workflow | None:
    w = store.get(workflow_id)
    if not w:
        return None
    if index < 0 or index >= len(w.steps):
        return None
    w.steps[index] = WorkflowStep.from_dict(step)
    w.version = int(w.version or 1) + 1
    return store.save(w)


def add_loop(
    workflow_id: str,
    *,
    index: int,
    count: int = 2,
    body: list[dict[str, Any]] | None = None,
    while_expr: str | None = None,
    as_var: str = "i",
) -> Workflow | None:
    args: dict[str, Any] = {"as": as_var}
    if while_expr:
        args["while"] = while_expr
        args["max"] = 50
    else:
        args["count"] = int(count)
    step = {
        "kind": "loop",
        "args": args,
        "steps": body or [],
    }
    return insert_step(workflow_id, index, step)


def add_condition(
    workflow_id: str,
    *,
    index: int,
    when: str,
    then_steps: list[dict[str, Any]] | None = None,
    else_steps: list[dict[str, Any]] | None = None,
) -> Workflow | None:
    step = {
        "kind": "if",
        "args": {"when": when},
        "steps": then_steps or [],
        "else_steps": else_steps or [],
    }
    return insert_step(workflow_id, index, step)


def create_blank(name: str, *, variables: dict[str, Any] | None = None) -> Workflow:
    wf = Workflow(
        id=store.new_id(name),
        name=name,
        description="Edited workflow",
        variables=dict(variables or {}),
        steps=[],
        tags=["edited"],
        channels=[],
    )
    return store.save(wf)
