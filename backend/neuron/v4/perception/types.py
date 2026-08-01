"""V4.2 perception result types — structured, confidence-aware, no fabricated success."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from neuron.v4.world.models import DesktopState, KnowledgeLevel


class PerceptionSource(str, Enum):
    WIN32 = "WIN32"
    UI_AUTOMATION = "UI_AUTOMATION"
    ACCESSIBILITY = "ACCESSIBILITY"
    BROWSER = "BROWSER"
    OCR = "OCR"
    SCREEN = "SCREEN"
    INFERRED = "INFERRED"
    COMPUTER_STATE = "COMPUTER_STATE"
    OBSERVE_DICT = "OBSERVE_DICT"


class PerceptionErrorCode(str, Enum):
    WINDOW_ENUM_FAILED = "WINDOW_ENUM_FAILED"
    UIA_TIMEOUT = "UIA_TIMEOUT"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    WINDOW_GONE = "WINDOW_GONE"
    ACCESS_DENIED = "ACCESS_DENIED"
    MONITOR_ENUM_FAILED = "MONITOR_ENUM_FAILED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class FullscreenKind(str, Enum):
    WINDOW_NORMAL = "WINDOW_NORMAL"
    WINDOW_MAXIMIZED = "WINDOW_MAXIMIZED"
    WINDOW_FULLSCREEN = "WINDOW_FULLSCREEN"
    MEDIA_FULLSCREEN = "MEDIA_FULLSCREEN"
    UNKNOWN = "UNKNOWN"


@dataclass
class PerceptionFailure:
    code: PerceptionErrorCode = PerceptionErrorCode.UNKNOWN
    source: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "source": self.source, "detail": self.detail[:200]}


@dataclass
class CaptureMeta:
    """Transient capture metadata — no permanent screenshot storage required."""

    bounds: dict[str, int] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    monitor_id: int | None = None
    window_hwnd: int = 0
    timestamp: float = 0.0
    path: str = ""  # optional temp path; callers should not rely on permanence
    kind: str = ""  # desktop | monitor | window | region
    fingerprint: str = ""  # cheap content fingerprint when computed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenDiffResult:
    changed: bool = False
    change_score: float = 0.0  # 0..1
    changed_regions: list[dict[str, Any]] = field(default_factory=list)
    window_changes: list[str] = field(default_factory=list)
    element_changes: list[str] = field(default_factory=list)
    foreground_changed: bool = False
    monitor_changed: bool = False
    confidence: float = 0.0
    before_fp: str = ""
    after_fp: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PerceptionResult:
    """Authoritative V4.2 observation package for DesktopWorldModel."""

    timestamp: float = field(default_factory=time.time)
    desktop: DesktopState = field(default_factory=DesktopState)
    sources_used: list[str] = field(default_factory=list)
    failures: list[PerceptionFailure] = field(default_factory=list)
    timing_ms: dict[str, float] = field(default_factory=dict)
    capture: CaptureMeta | None = None
    screen_diff: ScreenDiffResult | None = None
    ocr_available: bool | None = None  # None = not probed
    target: str = "desktop"  # desktop | window | monitor | region
    confidence: float = 0.0
    note: str = ""

    @property
    def ok(self) -> bool:
        """True if we got *some* usable structure — not 'task success'."""
        d = self.desktop
        return bool(
            d.monitors
            or d.windows
            or d.foreground_window
            or d.visible_elements
            or d.browser
        )

    @property
    def partial(self) -> bool:
        return bool(self.failures) and self.ok

    def to_observe_dict(self) -> dict[str, Any]:
        blob = self.desktop.to_observe_dict()
        blob["perception_v4"] = True
        blob["perception_confidence"] = self.confidence
        blob["perception_sources"] = list(self.sources_used)
        blob["perception_failures"] = [f.to_dict() for f in self.failures]
        blob["perception_timing_ms"] = dict(self.timing_ms)
        blob["observation_confidence"] = self.confidence
        if self.screen_diff:
            blob["ui_change"] = self.screen_diff.to_dict()
            blob["ui_changed"] = self.screen_diff.changed
        if self.capture:
            blob["capture_meta"] = self.capture.to_dict()
        return blob

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "ok": self.ok,
            "partial": self.partial,
            "confidence": self.confidence,
            "target": self.target,
            "sources_used": list(self.sources_used),
            "failures": [f.to_dict() for f in self.failures],
            "timing_ms": dict(self.timing_ms),
            "ocr_available": self.ocr_available,
            "screen_diff": self.screen_diff.to_dict() if self.screen_diff else None,
            "capture": self.capture.to_dict() if self.capture else None,
            "desktop": self.desktop.to_dict(),
            "note": self.note,
        }
