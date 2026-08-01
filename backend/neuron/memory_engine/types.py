"""Long-term memory types."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    CONVERSATION = "conversation"
    PROJECT = "project"
    DESKTOP = "desktop"
    PREFERENCE = "preference"


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class MemoryItem:
    kind: str
    content: str
    item_id: str = ""
    title: str = ""
    value: float = 1.0  # salience / reinforcement value
    pinned: bool = False  # remember forever
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_access: float = 0.0
    summary_of: list[str] = field(default_factory=list)  # ids compacted into this

    def __post_init__(self) -> None:
        if not self.item_id:
            self.item_id = _id(self.kind[:3] if self.kind else "mem")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryItem":
        return cls(
            kind=str(d.get("kind") or "semantic"),
            content=str(d.get("content") or ""),
            item_id=str(d.get("item_id") or ""),
            title=str(d.get("title") or ""),
            value=float(d.get("value") or 1.0),
            pinned=bool(d.get("pinned")),
            tags=list(d.get("tags") or []),
            meta=dict(d.get("meta") or {}),
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
            access_count=int(d.get("access_count") or 0),
            last_access=float(d.get("last_access") or 0),
            summary_of=list(d.get("summary_of") or []),
        )
