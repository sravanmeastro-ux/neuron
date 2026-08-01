"""Multi-device types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DeviceKind(str, Enum):
    DESKTOP = "desktop"
    LAPTOP = "laptop"
    REMOTE_PC = "remote_pc"
    VM = "vm"
    CLOUD = "cloud"


class SyncChannel(str, Enum):
    MEMORY = "memory"
    TASKS = "tasks"
    VOICE = "voice"
    PLUGINS = "plugins"
    PROJECTS = "projects"


class MDCapability(str, Enum):
    STATUS = "status"
    LIST = "list"
    REGISTER = "register"
    REMOVE = "remove"
    SYNC = "sync"
    SYNC_ALL = "sync_all"
    CONTROL = "control"
    PAIR = "pair"
    SELECT = "select"


@dataclass
class Device:
    id: str
    name: str
    kind: str = DeviceKind.DESKTOP.value
    host: str = "local"
    port: int = 8765
    online: bool = True
    role: str = "peer"  # local | peer | hub
    last_seen: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Device":
        d = d or {}
        return cls(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or d.get("id") or ""),
            kind=str(d.get("kind") or DeviceKind.DESKTOP.value),
            host=str(d.get("host") or "local"),
            port=int(d.get("port") or 8765),
            online=bool(d.get("online", True)),
            role=str(d.get("role") or "peer"),
            last_seen=float(d.get("last_seen") or 0.0),
            meta=dict(d.get("meta") or {}),
        )


@dataclass
class MDResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
