"""Computer Use Agent — operate any Windows application via composed systems."""

from __future__ import annotations

from neuron.computer_use.bridge import maybe_handle_computer_use
from neuron.computer_use.detect import looks_like_computer_use
from neuron.computer_use.agent import handle, tool_computer_use_agent
from neuron.computer_use.primitives import tool_drag_drop, tool_upload_file
from neuron.computer_use.scenarios import plan_actions

__all__ = [
    "maybe_handle_computer_use",
    "looks_like_computer_use",
    "handle",
    "tool_computer_use_agent",
    "tool_drag_drop",
    "tool_upload_file",
    "plan_actions",
]
