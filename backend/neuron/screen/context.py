"""Screen context memory — recent snapshots, buttons, focus."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from neuron.screen.types import ScreenElement, ScreenSnapshot

_LOCK = threading.Lock()
_MAX_SNAPS = 5


@dataclass
class ScreenMemory:
    current_window: str = ""
    application: str = ""
    focused_control: str = ""
    detected_buttons: list[dict[str, Any]] = field(default_factory=list)
    detected_text: list[str] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)
    last_query: str = ""
    last_click_name: str = ""
    updated_at: float = 0.0


_MEM = ScreenMemory()


def get_memory() -> ScreenMemory:
    return _MEM


def remember_snapshot(snap: ScreenSnapshot, *, query: str = "") -> None:
    with _LOCK:
        mem = _MEM
        mem.current_window = snap.window_title
        mem.application = snap.application
        focused = next((e for e in snap.elements if e.focused), None)
        mem.focused_control = (focused.name if focused else "") or ""
        mem.detected_buttons = [e.to_dict() for e in snap.buttons()[:40]]
        mem.detected_text = list(snap.ocr_text[:60])
        mem.last_query = query or mem.last_query
        mem.recent.append({
            "path": snap.path,
            "window": snap.window_title,
            "app": snap.application,
            "elements": len(snap.elements),
            "ts": snap.ts or time.time(),
        })
        mem.recent = mem.recent[-_MAX_SNAPS:]
        mem.updated_at = time.time()


def remember_click(name: str) -> None:
    with _LOCK:
        _MEM.last_click_name = name
        _MEM.updated_at = time.time()


def summary() -> dict[str, Any]:
    with _LOCK:
        m = _MEM
        return {
            "current_window": m.current_window,
            "application": m.application,
            "focused_control": m.focused_control,
            "button_count": len(m.detected_buttons),
            "text_preview": m.detected_text[:10],
            "last_query": m.last_query,
            "last_click_name": m.last_click_name,
            "recent_shots": len(m.recent),
        }
