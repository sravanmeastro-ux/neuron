"""NEURON Multi-Agent System — specialized agents that communicate via a bus."""

from __future__ import annotations

from neuron.agents.bridge import maybe_handle_multi_agent
from neuron.agents.coordinator import (
    get_coordinator,
    handle,
    looks_like_multi_agent,
    select_roles,
    tool_multi_agent_ask,
    tool_multi_agent_run,
    tool_multi_agent_status,
)
from neuron.agents.bus import get_bus, reset_bus
from neuron.agents.types import AgentRole

__all__ = [
    "maybe_handle_multi_agent",
    "looks_like_multi_agent",
    "select_roles",
    "handle",
    "get_coordinator",
    "get_bus",
    "reset_bus",
    "AgentRole",
    "tool_multi_agent_run",
    "tool_multi_agent_status",
    "tool_multi_agent_ask",
]
