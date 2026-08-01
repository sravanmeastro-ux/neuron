"""Screen Understanding types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScreenElement:
    """Unified UI element from UIA and/or OCR."""

    id: str
    name: str = ""
    role: str = ""  # button | menu | edit | checkbox | tab | dropdown | icon | text | window | taskbar | other
    source: str = ""  # uia | ocr | fused
    x: int = 0
    y: int = 0
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    width: int = 0
    height: int = 0
    confidence: float = 0.0
    enabled: bool = True
    focused: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def center(self) -> tuple[int, int]:
        if self.x or self.y:
            return self.x, self.y
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "source": self.source,
            "x": self.x,
            "y": self.y,
            "bbox": [self.left, self.top, self.right, self.bottom],
            "confidence": round(self.confidence, 3),
            "enabled": self.enabled,
            "focused": self.focused,
        }


@dataclass
class ScreenSnapshot:
    path: str = ""
    window_title: str = ""
    application: str = ""
    hwnd: int = 0
    elements: list[ScreenElement] = field(default_factory=list)
    ocr_text: list[str] = field(default_factory=list)
    vlm_summary: str = ""
    timings_ms: dict[str, float] = field(default_factory=dict)
    ts: float = 0.0

    def buttons(self) -> list[ScreenElement]:
        return [e for e in self.elements if e.role in ("button", "link", "menuitem", "tab")]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "window_title": self.window_title,
            "application": self.application,
            "hwnd": self.hwnd,
            "element_count": len(self.elements),
            "ocr_preview": self.ocr_text[:20],
            "vlm_summary": (self.vlm_summary or "")[:400],
            "timings_ms": dict(self.timings_ms),
            "ts": self.ts,
        }


@dataclass
class GroundedTarget:
    element: ScreenElement | None = None
    query: str = ""
    score: float = 0.0
    reason: str = ""
    alternatives: list[ScreenElement] = field(default_factory=list)


@dataclass
class ScreenPlan:
    action: str  # click | type | scroll | read | describe | close_popup | open_tab | none
    args: dict[str, Any] = field(default_factory=dict)
    say: str = ""
    needs_vlm: bool = False
    confidence: float = 0.0


@dataclass
class ScreenResult:
    ok: bool
    say: str = ""
    acted: bool = False
    snapshot: ScreenSnapshot | None = None
    plan: ScreenPlan | None = None
    grounded: GroundedTarget | None = None
    meta: dict[str, Any] = field(default_factory=dict)
