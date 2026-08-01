"""Persistent + in-memory task execution state."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from neuron.taskplan.types import Observation, TaskState, TaskStatus

_LOCK = threading.Lock()
_STATE: TaskState | None = None
_STORE = Path(__file__).resolve().parent.parent.parent / "data" / "taskplan_state.json"


def get_state() -> TaskState | None:
    return _STATE


def set_state(state: TaskState | None) -> None:
    global _STATE
    with _LOCK:
        _STATE = state
        if state is not None:
            _persist(state)


def clear_state() -> None:
    set_state(None)
    try:
        if _STORE.is_file():
            _STORE.unlink()
    except Exception:
        pass


def remember_observation(obs: Observation) -> None:
    with _LOCK:
        if _STATE is None:
            return
        _STATE.recent_observations.append(obs)
        _STATE.recent_observations = _STATE.recent_observations[-10:]
        if obs.application:
            _STATE.current_application = obs.application
        if obs.window_title:
            _STATE.focused_window = obs.window_title
        _STATE.updated_at = time.time()


def summary() -> dict[str, Any]:
    with _LOCK:
        if _STATE is None:
            return {"active": False}
        d = _STATE.to_dict()
        d["active"] = _STATE.status in (
            TaskStatus.RUNNING,
            TaskStatus.WAITING_CONFIRM,
            TaskStatus.PAUSED,
            TaskStatus.PLANNING,
        )
        return d


def _persist(state: TaskState) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    except Exception:
        pass


def load_persisted() -> TaskState | None:
    """Best-effort resume metadata (graph rebuilt on resume command)."""
    global _STATE
    try:
        if not _STORE.is_file():
            return None
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        st = TaskState(
            status=TaskStatus(data.get("status") or "paused"),
            current_subtask_id=str(data.get("current_subtask_id") or ""),
            completed_ids=list(data.get("completed_ids") or []),
            failed_ids=list(data.get("failed_ids") or []),
            pending_ids=list(data.get("pending_ids") or []),
            current_application=str(data.get("current_application") or ""),
            focused_window=str(data.get("focused_window") or ""),
            retry_count=int(data.get("retry_count") or 0),
            recovery_count=int(data.get("recovery_count") or 0),
            planner_ms=float(data.get("planner_ms") or 0),
            execution_ms=float(data.get("execution_ms") or 0),
            started_at=float(data.get("started_at") or 0),
            last_error=str(data.get("last_error") or ""),
            pending_confirm=data.get("pending_confirm"),
            say=str(data.get("say") or ""),
        )
        g = data.get("goal") or {}
        from neuron.taskplan.types import GoalSpec
        st.goal = GoalSpec(
            text=str(g.get("text") or ""),
            goal_id=str(g.get("goal_id") or ""),
            summary=str(g.get("summary") or ""),
            applications=list(g.get("applications") or []),
            completion_criteria=list(g.get("completion_criteria") or []),
            destructive=bool(g.get("destructive")),
        )
        _STATE = st
        return st
    except Exception:
        return None
