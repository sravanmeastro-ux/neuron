"""Autonomous Agent — upgrades Task Planner into full execution engine."""

from __future__ import annotations

from neuron.autonomous.engine import (
    handle_autonomous,
    plan_goal,
    run_autonomous,
    tool_autonomous_assess,
    tool_autonomous_progress,
    tool_autonomous_run,
)
from neuron.autonomous.progress import snapshot as progress_snapshot
from neuron.autonomous.risk import assess_plan

__all__ = [
    "handle_autonomous",
    "run_autonomous",
    "plan_goal",
    "tool_autonomous_run",
    "tool_autonomous_progress",
    "tool_autonomous_assess",
    "progress_snapshot",
    "assess_plan",
]
