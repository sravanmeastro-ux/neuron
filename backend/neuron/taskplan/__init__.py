"""Task Planning Engine — autonomous multi-step desktop workflows."""

from __future__ import annotations

from neuron.taskplan.bridge import maybe_handle_taskplan
from neuron.taskplan.detect import looks_like_workflow
from neuron.taskplan.engine import handle, cancel_active, tool_run_task_workflow
from neuron.taskplan.decompose import build_graph
from neuron.taskplan.extract import extract_goal
from neuron.taskplan import state as task_state

__all__ = [
    "maybe_handle_taskplan",
    "looks_like_workflow",
    "handle",
    "cancel_active",
    "tool_run_task_workflow",
    "build_graph",
    "extract_goal",
    "task_state",
]
