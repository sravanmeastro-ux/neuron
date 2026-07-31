"""V3.4 structured perception types — elements + observations (not screenshots-only)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# Canonical roles the ElementResolver / ReferenceResolver understand
ROLES = frozenset({
    "button",
    "link",
    "text_field",
    "browser_result",
    "menu_item",
    "file",
    "tab",
    "window",
    "video",
    "list_item",
    "checkbox",
    "other",
})


@dataclass
class PerceivedElement:
    """One actionable / observable UI target from any perception source."""

    id: str
    role: str = "other"
    name: str = ""
    application: str = ""
    window: str = ""
    monitor: int = 1
    interactive: bool = True
    clickable: bool = True
    bounds: dict[str, int] | None = None
    source: str = ""  # api | dom | uia | ocr | vision | coords
    confidence: float = 0.0
    index: int | None = None  # 1-based among same-role peers when known
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_ui_candidate(self) -> dict[str, Any]:
        """Shape expected by ReferenceResolver.ui_candidates."""
        return {
            "label": self.name,
            "name": self.name,
            "type": self.role,
            "role": self.role,
            "index": self.index,
            "id": self.id,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class Observation:
    """Structured screen/app observation — prefer this over raw screenshots."""

    elements: list[PerceivedElement] = field(default_factory=list)
    application: str = ""
    window: str = ""
    monitor: int = 1
    sources_used: list[str] = field(default_factory=list)
    vision_used: bool = False
    screenshot_path: str = ""
    url: str = ""
    note: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "elements": [e.to_dict() for e in self.elements],
            "application": self.application,
            "window": self.window,
            "monitor": self.monitor,
            "sources_used": list(self.sources_used),
            "vision_used": self.vision_used,
            "screenshot_path": self.screenshot_path,
            "url": self.url,
            "note": self.note,
            "error": self.error,
            "count": len(self.elements),
        }

    def ui_candidates(
        self, *, roles: set[str] | None = None, limit: int = 24
    ) -> list[dict[str, Any]]:
        pool = [
            el
            for el in self.elements
            if (not roles or el.role in roles) and (el.name or "").strip()
        ]
        pool.sort(key=lambda e: (e.index if e.index is not None else 10**6))
        return [el.as_ui_candidate() for el in pool[:limit]]

    def by_role(self, role: str) -> list[PerceivedElement]:
        r = (role or "").strip().lower()
        return [e for e in self.elements if (e.role or "").lower() == r]

    def compact(self, max_chars: int = 1200) -> str:
        lines = [
            f"app={self.application or '?'}",
            f"window={self.window or '?'}",
            f"monitor={self.monitor}",
            f"sources={','.join(self.sources_used) or 'none'}",
            f"vision_used={self.vision_used}",
        ]
        for i, e in enumerate(self.elements[:20], 1):
            lines.append(
                f"{i}. [{e.source}/{e.role}] {e.name[:60]!r} conf={e.confidence:.2f}"
            )
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
