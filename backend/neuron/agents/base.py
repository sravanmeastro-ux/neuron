"""Base specialist — thin adapter over existing NEURON cores."""

from __future__ import annotations

from typing import Any

from neuron.agents.bus import MessageBus
from neuron.agents.types import AgentMessage, AgentResult, AgentRole


class BaseAgent:
    role: AgentRole = AgentRole.COORDINATOR

    def __init__(self, bus: MessageBus | None = None) -> None:
        self.bus = bus

    @property
    def name(self) -> str:
        return self.role.value

    def register(self, bus: MessageBus) -> None:
        self.bus = bus
        bus.register(self.name, self.handle)

    def handle(self, message: AgentMessage) -> AgentResult:
        raise NotImplementedError

    def ask(self, to_role: str, payload: dict[str, Any] | None = None, **kw: Any) -> AgentResult:
        assert self.bus is not None
        return self.bus.request(to_role, payload, from_role=self.name, **kw)

    def ok(self, say: str = "", *, acted: bool = False, **data: Any) -> AgentResult:
        return AgentResult(ok=True, say=say, acted=acted, role=self.name, data=data)

    def fail(self, error: str, **data: Any) -> AgentResult:
        return AgentResult(ok=False, say=error, error=error, role=self.name, data=data)
