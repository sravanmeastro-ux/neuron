"""Multi-agent types — roles, messages, results."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    COORDINATOR = "coordinator"
    PLANNER = "planner"
    EXECUTOR = "executor"
    VISION = "vision"
    BROWSER = "browser"
    MEMORY = "memory"
    DESKTOP = "desktop"
    CODE = "code"
    RESEARCH = "research"


@dataclass
class AgentMessage:
    kind: str = "request"  # request | result | progress | clarify | cancel | broadcast
    from_role: str = ""
    to_role: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    message_id: str = ""
    priority: int = 0
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.message_id:
            self.message_id = uuid.uuid4().hex[:12]
        if not self.correlation_id:
            self.correlation_id = self.message_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    role: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    next_roles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SPECIALIST_ROLES = [
    AgentRole.PLANNER,
    AgentRole.EXECUTOR,
    AgentRole.VISION,
    AgentRole.BROWSER,
    AgentRole.MEMORY,
    AgentRole.DESKTOP,
    AgentRole.CODE,
    AgentRole.RESEARCH,
]
