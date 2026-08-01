"""Self-healing types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FaultKind(str, Enum):
    CRASH = "crash"
    FREEZE = "freeze"
    MEMORY_LEAK = "memory_leak"
    DEADLOCK = "deadlock"
    HIGH_CPU = "high_cpu"
    HIGH_RAM = "high_ram"
    HEALTHY = "healthy"


class SHCapability(str, Enum):
    STATUS = "status"
    SCAN = "scan"
    RECOVER = "recover"
    RESTART_MODULE = "restart_module"
    WATCHDOG_START = "watchdog_start"
    WATCHDOG_STOP = "watchdog_stop"
    WATCHDOG_STATUS = "watchdog_status"
    HEALTH = "health"


@dataclass
class Fault:
    kind: str
    severity: str = "medium"  # low|medium|high|critical
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    module: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SHResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    faults: list[dict[str, Any]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
