"""Computer Use Agent — types."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class CUStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CUAction:
    """One grounded computer action."""

    kind: str = ""  # click|type|key|scroll|drag|upload|open_app|open_website|screen|vision|wait|browser_*|tool
    args: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    expected: str = ""
    requires_confirm: bool = False
    action_id: str = ""

    def __post_init__(self) -> None:
        if not self.action_id:
            self.action_id = _id("act")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CUObservation:
    application: str = ""
    window_title: str = ""
    notes: str = ""
    elements: int = 0
    ocr_preview: list[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CUReport:
    goal: str = ""
    status: str = ""
    success: bool = False
    steps_total: int = 0
    steps_ok: int = 0
    steps_failed: int = 0
    recoveries: int = 0
    retries: int = 0
    planner_ms: float = 0.0
    execution_ms: float = 0.0
    say: str = ""
    path: str = "computer_use"
    actions: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
