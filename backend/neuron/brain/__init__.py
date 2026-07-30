"""NEURON brain package — closed-loop AgentLoop + ComputerState + ElementResolver."""

from neuron.brain.agent_loop import AgentLoop, run_agent_loop
from neuron.brain.computer_state import ComputerState, capture as capture_computer_state
from neuron.brain.element_resolver import (
    ResolvedTarget,
    click as click_element,
    resolve as resolve_element,
)

__all__ = [
    "AgentLoop",
    "run_agent_loop",
    "ComputerState",
    "capture_computer_state",
    "ResolvedTarget",
    "click_element",
    "resolve_element",
]
