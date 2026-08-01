"""Project Intelligence types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PICapability(str, Enum):
    STATUS = "status"
    INDEX = "index"
    OVERVIEW = "overview"
    LOCATE = "locate"
    LEAKS = "memory_leaks"
    GRAPH = "project_graph"
    ARCHITECTURE = "architecture"
    SEARCH = "search"


@dataclass
class PIResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
