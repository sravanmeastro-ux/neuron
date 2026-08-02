"""UI Grounding Engine types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class UGCapability(str, Enum):
    STATUS = "status"
    GROUND = "ground"
    CLICK = "click"
    PIPELINE = "pipeline"
    OBSERVE = "observe"


@dataclass
class GroundMatch:
    id: str = ""
    name: str = ""
    role: str = ""
    source: str = ""  # uia | ocr | icon | fused
    x: int = 0
    y: int = 0
    bbox: list[int] = field(default_factory=list)  # LTRB
    confidence: float = 0.0
    text_score: float = 0.0
    bbox_score: float = 0.0
    icon_score: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroundingResult:
    ok: bool = False
    say: str = ""
    acted: bool = False
    grounded: bool = False
    verified: bool = False
    target: str = ""
    match: GroundMatch | None = None
    confidence: float = 0.0
    attempts: int = 0
    scrolled: bool = False
    monitor: dict[str, Any] = field(default_factory=dict)
    dpi_scale: float = 1.0
    screenshot_path: str = ""
    elements: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.match is None:
            d["match"] = None
        return d


@dataclass
class UGResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
