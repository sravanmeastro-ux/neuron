"""Screen Understanding Engine — visual desktop perception + grounded actions."""

from __future__ import annotations

from neuron.screen.engine import handle, observe, tool_screen_understand
from neuron.screen.planner import is_visual_command
from neuron.screen import context as screen_context
from neuron.screen.types import ScreenResult, ScreenSnapshot

__all__ = [
    "handle",
    "observe",
    "tool_screen_understand",
    "is_visual_command",
    "screen_context",
    "ScreenResult",
    "ScreenSnapshot",
]
