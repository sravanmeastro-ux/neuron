"""Progress tracking snapshots for autonomous runs."""

from __future__ import annotations

from typing import Any

from neuron.taskplan.types import StepStatus, TaskState, TaskStatus


def snapshot(state: TaskState | None) -> dict[str, Any]:
    if state is None:
        return {"active": False, "progress_pct": 0, "status": "idle"}
    state.sync_from_graph()
    total = len(state.graph.subtasks) if state.graph else 0
    done = len(state.completed_ids or [])
    failed = len(state.failed_ids or [])
    pct = round(100.0 * done / total, 1) if total else 0.0
    current = ""
    if state.graph and state.current_subtask_id:
        for s in state.graph.subtasks:
            if s.subtask_id == state.current_subtask_id:
                current = s.description or s.action
                break
    return {
        "active": state.status in (
            TaskStatus.RUNNING,
            TaskStatus.WAITING_CONFIRM,
            TaskStatus.PLANNING,
            TaskStatus.PAUSED,
        ),
        "status": state.status.value,
        "goal": state.goal.summary or state.goal.text,
        "progress_pct": pct,
        "steps_total": total,
        "steps_completed": done,
        "steps_failed": failed,
        "steps_pending": len(state.pending_ids or []),
        "current_subtask": current,
        "current_application": state.current_application,
        "focused_window": state.focused_window,
        "retry_count": state.retry_count,
        "recovery_count": state.recovery_count,
        "last_error": state.last_error,
        "needs_confirm": bool(state.pending_confirm),
        "pending_confirm": state.pending_confirm,
    }


def step_table(state: TaskState | None) -> list[dict[str, Any]]:
    if not state or not state.graph:
        return []
    rows = []
    for s in state.graph.subtasks:
        rows.append({
            "id": s.subtask_id,
            "action": s.action,
            "description": s.description,
            "status": s.status.value if isinstance(s.status, StepStatus) else str(s.status),
            "attempts": s.attempt_count,
            "requires_confirm": s.requires_confirm,
            "error": s.last_error[:160] if s.last_error else "",
        })
    return rows
