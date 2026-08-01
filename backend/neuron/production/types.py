"""Production readiness types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ProdCapability(str, Enum):
    STATUS = "status"
    AUDIT = "audit"
    DIAGNOSTICS = "diagnostics"
    WIZARD = "wizard"
    INSTALL = "install"
    UPDATE = "update"
    REPORT = "report"


@dataclass
class CheckResult:
    area: str
    name: str
    ok: bool
    severity: str = "info"  # info|warn|fail
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProdResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
