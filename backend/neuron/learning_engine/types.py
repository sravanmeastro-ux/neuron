"""Learning Engine — reinforcement scores and habit records."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ScoredItem:
    key: str
    category: str  # app|website|browser|editor|folder|monitor|workflow|hotkey|schedule
    score: float = 0.0
    count: int = 0
    success: int = 0
    fail: int = 0
    last_ts: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolEvent:
    tool: str
    args: dict[str, Any]
    ok: bool
    ts: float = field(default_factory=time.time)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": dict(self.args or {}),
            "ok": self.ok,
            "ts": self.ts,
            "detail": self.detail,
        }


# EWMA / reinforcement defaults
ALPHA_SUCCESS = 0.25
ALPHA_FAIL = 0.15
REWARD_SUCCESS = 1.0
REWARD_FAIL = -0.4
DECAY_HALF_LIFE_DAYS = 14.0
