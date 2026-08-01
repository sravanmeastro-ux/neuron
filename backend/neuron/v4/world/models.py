"""V4.1 typed desktop entities — authoritative shapes for DesktopWorldModel.

Legacy mapping (do not delete sources yet):
  ComputerState  → live capture (adapters.from_computer_state)
  v3.WorldState  → verified focus subset (adapters.from_world_state / sync_to)
  v3.Observation → elements + app/window (adapters.from_v3_observation)
  ScreenContext  → perception slice (adapters.from_screen_context)
  observe_world dict → AgentLoop observation blob
"""

from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class KnowledgeLevel(str, Enum):
    """How strongly we know a fact. Never invent KNOWN from nothing."""

    KNOWN = "known"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


@dataclass
class FieldKnowledge:
    """Optional annotation for an inferred field."""

    level: KnowledgeLevel = KnowledgeLevel.UNKNOWN
    confidence: float = 0.0  # 0..1
    source: str = ""


@dataclass
class MonitorState:
    id: int = 0
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    work_left: int | None = None
    work_top: int | None = None
    work_width: int | None = None
    work_height: int | None = None
    primary: bool = False
    roles: list[str] = field(default_factory=list)  # main/left/right/other/…
    dpi_scale: float | None = None
    label: str = ""
    confidence: float = 1.0
    knowledge: KnowledgeLevel = KnowledgeLevel.KNOWN

    @property
    def center_x(self) -> int:
        return int(self.left) + int(self.width) // 2

    @property
    def center_y(self) -> int:
        return int(self.top) + int(self.height) // 2

    def contains_point(self, x: int, y: int) -> bool:
        return (
            int(self.left) <= int(x) < int(self.left) + max(1, int(self.width))
            and int(self.top) <= int(y) < int(self.top) + max(1, int(self.height))
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["knowledge"] = self.knowledge.value
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "MonitorState":
        raw = raw or {}
        mid = raw.get("id") if raw.get("id") is not None else raw.get("monitor_id")
        try:
            mid_i = int(mid or 0)
        except (TypeError, ValueError):
            mid_i = 0
        knowledge = raw.get("knowledge") or KnowledgeLevel.KNOWN
        if isinstance(knowledge, str):
            try:
                knowledge = KnowledgeLevel(knowledge)
            except ValueError:
                knowledge = KnowledgeLevel.KNOWN
        return cls(
            id=mid_i,
            left=int(raw.get("left") or 0),
            top=int(raw.get("top") or 0),
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            work_left=_opt_int(raw.get("work_left")),
            work_top=_opt_int(raw.get("work_top")),
            work_width=_opt_int(raw.get("work_width")),
            work_height=_opt_int(raw.get("work_height")),
            primary=bool(raw.get("primary") or raw.get("is_primary")),
            roles=list(raw.get("roles") or []),
            dpi_scale=_opt_float(raw.get("dpi_scale") or raw.get("scale")),
            label=str(raw.get("label") or "")[:40],
            confidence=float(raw.get("confidence") if raw.get("confidence") is not None else 1.0),
            knowledge=knowledge if isinstance(knowledge, KnowledgeLevel) else KnowledgeLevel.KNOWN,
        )


@dataclass
class WindowState:
    hwnd: int = 0
    title: str = ""
    process: str = ""
    application: str = ""
    monitor_id: int | None = None
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None
    focused: bool = False
    visible: bool | None = None
    minimized: bool | None = None
    maximized: bool | None = None
    fullscreen: bool | None = None
    confidence: float = 0.0
    knowledge: KnowledgeLevel = KnowledgeLevel.UNKNOWN
    application_knowledge: KnowledgeLevel = KnowledgeLevel.UNKNOWN

    def bounds_dict(self) -> dict[str, int] | None:
        if self.left is None or self.top is None or self.width is None or self.height is None:
            return None
        return {
            "left": int(self.left),
            "top": int(self.top),
            "width": int(self.width),
            "height": int(self.height),
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["knowledge"] = self.knowledge.value
        d["application_knowledge"] = self.application_knowledge.value
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "WindowState":
        raw = raw or {}
        app = str(raw.get("application") or raw.get("app") or "")[:80]
        process = str(raw.get("process") or "")[:80]
        app_know = KnowledgeLevel.KNOWN if (app and raw.get("app")) or process else KnowledgeLevel.UNKNOWN
        if app and not process and not raw.get("app"):
            # title-only inference
            app_know = KnowledgeLevel.INFERRED
        title = str(raw.get("title") or "")[:160]
        if not app and title:
            app = _app_from_title(title)
            app_know = KnowledgeLevel.INFERRED if app else KnowledgeLevel.UNKNOWN
        mon = raw.get("monitor_id")
        if mon is None:
            mon = raw.get("monitor")
        try:
            mon_i = int(mon) if mon is not None else None
        except (TypeError, ValueError):
            mon_i = None
        hwnd = 0
        try:
            hwnd = int(raw.get("hwnd") or 0)
        except (TypeError, ValueError):
            hwnd = 0
        conf = float(raw.get("confidence") if raw.get("confidence") is not None else 0.0)
        knowledge = KnowledgeLevel.KNOWN if (hwnd or title) else KnowledgeLevel.UNKNOWN
        if mon_i is not None and conf < 0.5:
            conf = 0.85  # geometry-mapped monitor is usually high confidence
        return cls(
            hwnd=hwnd,
            title=title,
            process=process,
            application=app,
            monitor_id=mon_i,
            left=_opt_int(raw.get("left")),
            top=_opt_int(raw.get("top")),
            width=_opt_int(raw.get("width")),
            height=_opt_int(raw.get("height")),
            focused=bool(raw.get("focused")),
            visible=_opt_bool(raw.get("visible")),
            minimized=_opt_bool(raw.get("minimized")),
            maximized=_opt_bool(raw.get("maximized")),
            fullscreen=_opt_bool(raw.get("fullscreen")),
            confidence=conf or (0.9 if hwnd else 0.4 if title else 0.0),
            knowledge=knowledge,
            application_knowledge=app_know,
        )


@dataclass
class ApplicationState:
    name: str = ""
    process: str = ""
    focused: bool = False
    window_hwnds: list[int] = field(default_factory=list)
    confidence: float = 0.0
    knowledge: KnowledgeLevel = KnowledgeLevel.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["knowledge"] = self.knowledge.value
        return d


@dataclass
class BrowserState:
    browser: str = ""
    window_hwnd: int = 0
    tab_title: str = ""
    url: str = ""
    page_type: str = ""  # search | watch | home | unknown | ""
    media_state: str = ""  # playing | paused | unknown | ""
    fullscreen: bool | None = None  # media/player fullscreen when known
    visible_elements: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    knowledge: KnowledgeLevel = KnowledgeLevel.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["knowledge"] = self.knowledge.value
        return d


@dataclass
class UIElementState:
    id: str = ""
    role: str = "other"
    name: str = ""
    text: str = ""
    bounds: dict[str, int] | None = None
    source: str = ""  # uia | dom | ocr | vision | api | coords
    application: str = ""
    window: str = ""
    monitor_id: int | None = None
    interactive: bool = True
    clickable: bool = True
    confidence: float = 0.0
    knowledge: KnowledgeLevel = KnowledgeLevel.INFERRED
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["knowledge"] = self.knowledge.value
        return d


@dataclass
class InteractionRecord:
    timestamp: float = 0.0
    action: str = ""
    target: str = ""
    application: str = ""
    window: str = ""
    monitor_id: int | None = None
    result: str = ""
    ok: bool | None = None
    task_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DesktopState:
    """Immutable-style snapshot of the desktop at one moment.

    Mutate only via DesktopWorldModel.update_* which replaces the snapshot.
    """

    monitors: list[MonitorState] = field(default_factory=list)
    windows: list[WindowState] = field(default_factory=list)
    foreground_window: WindowState | None = None
    foreground_application: ApplicationState | None = None
    active_monitor_id: int | None = None
    cursor_x: int | None = None
    cursor_y: int | None = None
    cursor_monitor_id: int | None = None
    focused_element: UIElementState | None = None
    visible_elements: list[UIElementState] = field(default_factory=list)
    browser: BrowserState | None = None
    recent_interactions: list[InteractionRecord] = field(default_factory=list)
    timestamp: float = 0.0
    observation_confidence: float = 0.0
    fingerprint: str = ""
    sources: list[str] = field(default_factory=list)
    scene: str = ""
    ocr_text: list[str] = field(default_factory=list)
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "DesktopState":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitors": [m.to_dict() for m in self.monitors],
            "windows": [w.to_dict() for w in self.windows],
            "foreground_window": self.foreground_window.to_dict() if self.foreground_window else None,
            "foreground_application": (
                self.foreground_application.to_dict() if self.foreground_application else None
            ),
            "active_monitor_id": self.active_monitor_id,
            "cursor": {
                "x": self.cursor_x,
                "y": self.cursor_y,
                "monitor": self.cursor_monitor_id,
            },
            "focused_element": self.focused_element.to_dict() if self.focused_element else None,
            "visible_elements": [e.to_dict() for e in self.visible_elements],
            "browser": self.browser.to_dict() if self.browser else None,
            "recent_interactions": [r.to_dict() for r in self.recent_interactions],
            "timestamp": self.timestamp,
            "observation_confidence": self.observation_confidence,
            "fingerprint": self.fingerprint or self.compute_fingerprint(),
            "sources": list(self.sources),
            "scene": self.scene,
            "ocr_text": list(self.ocr_text)[:40],
            "error": self.error,
        }

    def compute_fingerprint(self) -> str:
        fw = self.foreground_window
        br = self.browser
        parts = [
            (fw.title if fw else "")[:80],
            str(fw.hwnd if fw else ""),
            (self.foreground_application.name if self.foreground_application else ""),
            str(self.active_monitor_id if self.active_monitor_id is not None else ""),
            (br.url if br else "")[:120],
            ",".join(sorted((e.name or "")[:40] for e in self.visible_elements[:20] if e.name)),
        ]
        raw = "|".join(parts)
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]

    def ensure_fingerprint(self) -> str:
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()
        return self.fingerprint

    def to_observe_dict(self) -> dict[str, Any]:
        """Shape compatible with verifier.observe_world / WorldState.apply_observation."""
        fw = self.foreground_window
        app = self.foreground_application.name if self.foreground_application else ""
        if not app and fw:
            app = fw.application
        return {
            "app": app or "?",
            "window": (fw.title if fw else "") or "",
            "hwnd": int(fw.hwnd if fw else 0),
            "url": (self.browser.url if self.browser else "") or "",
            "browser_url": (self.browser.url if self.browser else "") or "",
            "browser_title": (self.browser.tab_title if self.browser else "") or "",
            "scene": self.scene or "",
            "focused_monitor": self.active_monitor_id,
            "monitor": self.active_monitor_id,
            "active_application": app or "",
            "active_app": app or "",
            "cursor": {
                "x": self.cursor_x,
                "y": self.cursor_y,
                "monitor": self.cursor_monitor_id,
            },
            "monitors": [m.to_dict() for m in self.monitors],
            "windows": [w.to_dict() for w in self.windows],
            "open_windows": [w.to_dict() for w in self.windows],
            "visible_text": list(self.ocr_text)[:40],
            "ocr_text": list(self.ocr_text)[:40],
            "clickables": [
                e.to_dict() for e in self.visible_elements if e.clickable
            ][:20],
            "fingerprint": self.ensure_fingerprint(),
            "observation_confidence": self.observation_confidence,
            "sources": list(self.sources),
            "desktop_world_model": True,
        }


def _opt_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_bool(v: Any) -> bool | None:
    if v is None:
        return None
    return bool(v)


def _app_from_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return ""
    # "Document - App" → App
    if " - " in t:
        return t.rsplit(" - ", 1)[-1].strip()[:60]
    low = t.lower()
    for name in (
        "chrome", "edge", "firefox", "opera", "brave", "spotify", "discord",
        "blender", "notepad", "code", "cursor", "explorer", "steam",
    ):
        if name in low:
            return name.title() if name != "code" else "Code"
    return t[:40]
