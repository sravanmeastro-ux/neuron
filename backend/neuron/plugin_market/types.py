"""Plugin Market types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MarketCapability(str, Enum):
    STATUS = "status"
    INSTALL = "install"
    UNINSTALL = "uninstall"
    UPDATE = "update"
    UPDATE_ALL = "update_all"
    HOT_RELOAD = "hot_reload"
    WATCH_START = "watch_start"
    WATCH_STOP = "watch_stop"
    SCAFFOLD = "scaffold"
    LIST = "list"
    TRUST = "trust"
    CATALOG = "catalog"


@dataclass
class MarketResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
