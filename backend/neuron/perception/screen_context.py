"""Structured screen perception result (Phase 5)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ScreenContext:
    monitor: int = 1
    application: str = ""
    title: str = ""
    visible_text: list[str] = field(default_factory=list)
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    vision_description: str = ""
    cursor: dict[str, int] | None = None
    sources: list[str] = field(default_factory=list)  # uia | ocr | vlm | capture
    screenshot_path: str = ""
    bounds: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compact(self, max_chars: int = 1800) -> str:
        """Planner-friendly text blob."""
        lines = [
            f"monitor={self.monitor}",
            f"app={self.application or '?'}",
            f"title={self.title or '?'}",
        ]
        if self.cursor:
            lines.append(f"cursor=({self.cursor.get('x')},{self.cursor.get('y')})")
        if self.ui_elements:
            labels = []
            for e in self.ui_elements[:18]:
                n = e.get("name") or e.get("text") or ""
                t = e.get("control_type") or e.get("role") or ""
                if n:
                    labels.append(f"{t}:{n}" if t else n)
            if labels:
                lines.append("ui=[" + "; ".join(labels)[:700] + "]")
        if self.visible_text:
            lines.append("ocr=[" + " | ".join(self.visible_text[:20])[:500] + "]")
        if self.vision_description:
            lines.append("vision=" + self.vision_description[:500])
        if self.sources:
            lines.append("sources=" + ",".join(self.sources))
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def __str__(self) -> str:
        return self.compact()
