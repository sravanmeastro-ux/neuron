"""Workflow Intelligence types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class WICapability(str, Enum):
    STATUS = "status"
    OBSERVE = "observe"
    LEARN = "learn"
    ENSURE = "ensure_presets"
    RUN = "run"
    LIST = "list"
    SUGGEST = "suggest"


@dataclass
class WIResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
