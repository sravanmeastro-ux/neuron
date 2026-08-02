"""Detect UI elements + icon-like regions for grounding."""

from __future__ import annotations

from typing import Any

from neuron.screen.detect import build_snapshot
from neuron.screen.types import ScreenElement, ScreenSnapshot


def detect_elements(*, use_ocr: bool = True, use_uia: bool = True) -> ScreenSnapshot:
    return build_snapshot(use_ocr=use_ocr, use_uia=use_uia)


def icon_candidates(snap: ScreenSnapshot) -> list[ScreenElement]:
    """Elements that look like icons (ImageControl / small square / role=icon)."""
    icons = []
    for el in snap.elements:
        if el.role == "icon":
            icons.append(el)
            continue
        w, h = el.width, el.height
        if el.source == "uia" and 12 <= w <= 64 and 12 <= h <= 64 and abs(w - h) <= 16:
            # likely toolbar icon
            clone = ScreenElement(
                id=el.id + "-iconish",
                name=el.name or "icon",
                role="icon",
                source=el.source,
                x=el.x,
                y=el.y,
                left=el.left,
                top=el.top,
                right=el.right,
                bottom=el.bottom,
                width=w,
                height=h,
                confidence=max(0.4, el.confidence * 0.8),
                enabled=el.enabled,
                meta={**(el.meta or {}), "iconish": True},
            )
            icons.append(clone)
    return icons


def elements_as_dicts(snap: ScreenSnapshot) -> list[dict[str, Any]]:
    return [e.to_dict() for e in snap.elements[:80]]
