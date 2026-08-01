"""Adapters: legacy V3 state → V4 DesktopState (and limited reverse sync).

Ownership rule:
  DesktopWorldModel is the V4 source of truth for *structured* desktop state.
  ComputerState remains the live capture composer.
  v3.WorldState remains the *verified* ContextEngine picture.
  Adapters normalize; they do not create a second independently mutating copy
  inside AgentLoop — loop pushes observe_world dicts into DesktopWorldModel.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.v4.world.models import (
    ApplicationState,
    BrowserState,
    DesktopState,
    KnowledgeLevel,
    MonitorState,
    UIElementState,
    WindowState,
)


def from_observe_dict(raw: dict[str, Any] | None, *, previous: DesktopState | None = None) -> DesktopState:
    """Normalize verifier.observe_world / ComputerState.to_observe_dict blobs."""
    raw = dict(raw or {})
    prev_interactions = list(previous.recent_interactions) if previous else []

    monitors = [
        MonitorState.from_dict(m) for m in (raw.get("monitors") or []) if isinstance(m, dict)
    ]
    win_raw = raw.get("windows") or raw.get("open_windows") or []
    windows = [WindowState.from_dict(w) for w in win_raw if isinstance(w, dict)]

    hwnd = 0
    try:
        hwnd = int(raw.get("hwnd") or raw.get("focused_hwnd") or 0)
    except (TypeError, ValueError):
        hwnd = 0
    title = str(raw.get("window") or raw.get("focused_window_title") or raw.get("title") or "")[:160]
    app_name = str(
        raw.get("active_application")
        or raw.get("app")
        or raw.get("active_app")
        or ""
    )[:80]
    mon = raw.get("focused_monitor")
    if mon is None:
        mon = raw.get("monitor") or raw.get("active_monitor")
    try:
        mon_i = int(mon) if mon is not None else None
    except (TypeError, ValueError):
        mon_i = None

    app_know = KnowledgeLevel.KNOWN if app_name and raw.get("active_application") else KnowledgeLevel.UNKNOWN
    if app_name and not raw.get("active_application") and not raw.get("app"):
        app_know = KnowledgeLevel.INFERRED
    if not app_name and title:
        from neuron.v4.world.models import _app_from_title
        app_name = _app_from_title(title)
        app_know = KnowledgeLevel.INFERRED if app_name else KnowledgeLevel.UNKNOWN

    fg = None
    if hwnd or title:
        # Prefer matching open window
        match = next((w for w in windows if hwnd and w.hwnd == hwnd), None)
        if match is None and title:
            low = title.lower()
            match = next((w for w in windows if low in (w.title or "").lower()), None)
        if match:
            fg = WindowState.from_dict(match.to_dict())
            fg.focused = True
            if app_name:
                fg.application = app_name
                fg.application_knowledge = app_know
            if mon_i is not None:
                fg.monitor_id = mon_i
        else:
            fg = WindowState(
                hwnd=hwnd,
                title=title,
                application=app_name,
                monitor_id=mon_i,
                focused=True,
                confidence=0.9 if hwnd else 0.5,
                knowledge=KnowledgeLevel.KNOWN if (hwnd or title) else KnowledgeLevel.UNKNOWN,
                application_knowledge=app_know,
            )
            windows = [fg] + [w for w in windows if not (hwnd and w.hwnd == hwnd)]

    # Mark focused flag on list
    for w in windows:
        w.focused = bool(hwnd and w.hwnd == hwnd) or (
            bool(title) and (w.title or "").strip() == title.strip()
        )

    app_state = None
    if app_name:
        app_state = ApplicationState(
            name=app_name,
            process="",
            focused=True,
            window_hwnds=[fg.hwnd] if fg and fg.hwnd else [],
            confidence=0.9 if app_know is KnowledgeLevel.KNOWN else 0.55,
            knowledge=app_know,
        )

    cursor = raw.get("cursor") if isinstance(raw.get("cursor"), dict) else {}
    cx = cursor.get("x")
    cy = cursor.get("y")
    try:
        cx_i = int(cx) if cx is not None else None
        cy_i = int(cy) if cy is not None else None
    except (TypeError, ValueError):
        cx_i = cy_i = None
    cmon = cursor.get("monitor")
    try:
        cmon_i = int(cmon) if cmon is not None else None
    except (TypeError, ValueError):
        cmon_i = None

    url = str(raw.get("url") or raw.get("browser_url") or "")[:400]
    btitle = str(raw.get("browser_title") or "")[:160]
    browser = None
    if url or btitle or raw.get("browser_elements"):
        browser = BrowserState(
            browser=_browser_name(app_name),
            window_hwnd=hwnd,
            tab_title=btitle or title,
            url=url,
            page_type=_page_type(url),
            visible_elements=list(raw.get("browser_elements") or [])[:30],
            confidence=0.85 if url else 0.4,
            knowledge=KnowledgeLevel.KNOWN if url else KnowledgeLevel.INFERRED,
        )

    elements: list[UIElementState] = []
    for e in raw.get("clickables") or raw.get("ui_elements") or raw.get("visible_elements") or []:
        if not isinstance(e, dict):
            continue
        elements.append(_element_from_dict(e, app_name=app_name, window=title, monitor=mon_i))

    ocr = list(raw.get("ocr_text") or raw.get("visible_text") or [])[:40]
    sources = list(raw.get("sources") or raw.get("screen_sources") or [])
    if raw.get("computer_state"):
        sources = list(dict.fromkeys(sources + ["computer_state"]))
    if raw.get("desktop_world_model"):
        sources = list(dict.fromkeys(sources + ["desktop_world_model"]))

    conf = raw.get("observation_confidence")
    try:
        conf_f = float(conf) if conf is not None else _estimate_confidence(hwnd, title, monitors, elements)
    except (TypeError, ValueError):
        conf_f = _estimate_confidence(hwnd, title, monitors, elements)

    state = DesktopState(
        monitors=monitors,
        windows=windows,
        foreground_window=fg,
        foreground_application=app_state,
        active_monitor_id=mon_i,
        cursor_x=cx_i,
        cursor_y=cy_i,
        cursor_monitor_id=cmon_i,
        visible_elements=elements,
        browser=browser,
        recent_interactions=prev_interactions,
        timestamp=float(raw.get("timestamp") or raw.get("captured_at") or time.time()),
        observation_confidence=conf_f,
        fingerprint=str(raw.get("fingerprint") or raw.get("fingerprint_value") or ""),
        sources=sources,
        scene=str(raw.get("scene") or "")[:40],
        ocr_text=[str(x)[:120] for x in ocr],
        error=str(raw["error"]) if raw.get("error") else None,
        raw={k: v for k, v in raw.items() if k not in ("computer_state",)},
    )
    state.ensure_fingerprint()
    return state


def from_computer_state(cs: Any, *, previous: DesktopState | None = None) -> DesktopState:
    """Adapter: neuron.brain.computer_state.ComputerState → DesktopState."""
    if cs is None:
        return DesktopState(timestamp=time.time())
    if hasattr(cs, "to_observe_dict"):
        blob = cs.to_observe_dict()
    elif isinstance(cs, dict):
        blob = cs
    else:
        blob = {}
    # Enrich with full lists ComputerState holds
    try:
        blob.setdefault("monitors", list(getattr(cs, "monitors", None) or []))
        blob.setdefault("open_windows", list(getattr(cs, "open_windows", None) or []))
        blob.setdefault("ui_elements", list(getattr(cs, "ui_elements", None) or []))
        blob.setdefault("clickables", list(getattr(cs, "clickable_elements", None) or cs.clickables(limit=30)))
        blob.setdefault("browser_elements", list(getattr(cs, "browser_elements", None) or []))
        blob.setdefault("ocr_text", list(getattr(cs, "ocr_text", None) or []))
        blob.setdefault("visible_text", list(getattr(cs, "visible_text", None) or []))
        blob.setdefault("sources", list(getattr(cs, "sources", None) or []))
        blob.setdefault("scene", getattr(cs, "scene", "") or "")
        blob.setdefault("captured_at", getattr(cs, "captured_at", 0) or time.time())
        blob["computer_state"] = True
    except Exception:
        pass
    return from_observe_dict(blob, previous=previous)


def from_world_state(ws: Any, *, previous: DesktopState | None = None) -> DesktopState:
    """Adapter: neuron.v3.world_state.WorldState → DesktopState (verified subset)."""
    if ws is None:
        return DesktopState(timestamp=time.time())
    blob = {
        "active_application": getattr(ws, "active_app", "") or "",
        "window": getattr(ws, "active_window", "") or "",
        "hwnd": getattr(ws, "active_hwnd", 0) or 0,
        "focused_monitor": getattr(ws, "active_monitor", None),
        "monitors": list(getattr(ws, "monitors", None) or []),
        "windows": list(getattr(ws, "windows", None) or []),
        "browser_url": getattr(ws, "browser_url", "") or "",
        "browser_title": getattr(ws, "browser_title", "") or "",
        "scene": getattr(ws, "scene", "") or "",
        "fingerprint": getattr(ws, "observation_fingerprint", "") or "",
        "timestamp": getattr(ws, "updated_at", 0) or time.time(),
        "sources": ["v3_world_state"],
        "observation_confidence": 0.8,
    }
    return from_observe_dict(blob, previous=previous)


def from_v3_observation(obs: Any, *, previous: DesktopState | None = None) -> DesktopState:
    """Adapter: neuron.v3.perception_types.Observation → DesktopState."""
    if obs is None:
        return DesktopState(timestamp=time.time())
    elements = []
    for e in getattr(obs, "elements", None) or []:
        elements.append(
            UIElementState(
                id=str(getattr(e, "id", "") or ""),
                role=str(getattr(e, "role", "other") or "other"),
                name=str(getattr(e, "name", "") or ""),
                text=str(getattr(e, "name", "") or ""),
                bounds=getattr(e, "bounds", None),
                source=str(getattr(e, "source", "") or ""),
                application=str(getattr(e, "application", "") or ""),
                window=str(getattr(e, "window", "") or ""),
                monitor_id=int(getattr(e, "monitor", 0) or 0) or None,
                interactive=bool(getattr(e, "interactive", True)),
                clickable=bool(getattr(e, "clickable", True)),
                confidence=float(getattr(e, "confidence", 0) or 0),
                knowledge=KnowledgeLevel.INFERRED,
            )
        )
    base = previous.clone() if previous else DesktopState()
    base.visible_elements = elements
    base.foreground_application = ApplicationState(
        name=str(getattr(obs, "application", "") or ""),
        focused=True,
        confidence=0.7,
        knowledge=KnowledgeLevel.INFERRED if getattr(obs, "application", None) else KnowledgeLevel.UNKNOWN,
    ) if getattr(obs, "application", None) else base.foreground_application
    if getattr(obs, "window", None):
        base.foreground_window = WindowState(
            title=str(obs.window)[:160],
            application=str(getattr(obs, "application", "") or ""),
            monitor_id=int(getattr(obs, "monitor", 0) or 0) or None,
            focused=True,
            confidence=0.7,
            knowledge=KnowledgeLevel.INFERRED,
            application_knowledge=KnowledgeLevel.INFERRED,
        )
    try:
        base.active_monitor_id = int(getattr(obs, "monitor", 0) or 0) or base.active_monitor_id
    except (TypeError, ValueError):
        pass
    if getattr(obs, "url", None):
        base.browser = BrowserState(
            url=str(obs.url)[:400],
            tab_title=str(getattr(obs, "window", "") or ""),
            knowledge=KnowledgeLevel.KNOWN,
            confidence=0.8,
        )
    base.sources = list(dict.fromkeys(list(base.sources) + list(getattr(obs, "sources_used", None) or []) + ["v3_observation"]))
    base.timestamp = time.time()
    base.observation_confidence = 0.65
    if getattr(obs, "error", None):
        base.error = str(obs.error)
    base.fingerprint = ""
    base.ensure_fingerprint()
    return base


def from_screen_context(sc: Any, *, previous: DesktopState | None = None) -> DesktopState:
    """Adapter: neuron.perception.screen_context.ScreenContext → DesktopState."""
    if sc is None:
        return DesktopState(timestamp=time.time())
    blob = {
        "focused_monitor": getattr(sc, "monitor", None),
        "active_application": getattr(sc, "application", "") or "",
        "window": getattr(sc, "title", "") or "",
        "ui_elements": list(getattr(sc, "ui_elements", None) or []),
        "visible_text": list(getattr(sc, "visible_text", None) or []),
        "cursor": dict(getattr(sc, "cursor", None) or {}) if getattr(sc, "cursor", None) else {},
        "sources": list(getattr(sc, "sources", None) or []) + ["screen_context"],
        "scene": "",
        "error": getattr(sc, "error", None),
        "observation_confidence": 0.6,
    }
    return from_observe_dict(blob, previous=previous)


def sync_world_state_from_desktop(ws: Any, state: DesktopState) -> None:
    """Push DesktopState into an existing v3.WorldState via apply_observation."""
    if ws is None or state is None:
        return
    try:
        ws.apply_observation(state.to_observe_dict())
    except Exception:
        pass


def _element_from_dict(
    e: dict[str, Any],
    *,
    app_name: str = "",
    window: str = "",
    monitor: int | None = None,
) -> UIElementState:
    name = str(e.get("name") or e.get("label") or e.get("text") or "")[:120]
    role = str(e.get("role") or e.get("control_type") or e.get("type") or "other")[:40]
    bounds = None
    if e.get("bounds"):
        bounds = e.get("bounds")
    elif e.get("center_x") is not None and e.get("center_y") is not None:
        bounds = {"center_x": int(e["center_x"]), "center_y": int(e["center_y"])}
    conf = float(e.get("confidence") if e.get("confidence") is not None else 0.5)
    return UIElementState(
        id=str(e.get("id") or name or role)[:80],
        role=role.lower().replace("control", "") or "other",
        name=name,
        text=str(e.get("text") or name)[:120],
        bounds=bounds if isinstance(bounds, dict) else None,
        source=str(e.get("source") or "uia")[:20],
        application=str(e.get("application") or app_name)[:80],
        window=str(e.get("window") or window)[:120],
        monitor_id=_as_int_or_none(e.get("monitor") if e.get("monitor") is not None else monitor),
        interactive=bool(e.get("interactive", True)),
        clickable=bool(e.get("clickable", True)),
        confidence=conf,
        knowledge=KnowledgeLevel.INFERRED,
        attributes={k: v for k, v in e.items() if k not in ("name", "label", "text", "role", "bounds")},
    )


def _estimate_confidence(
    hwnd: int,
    title: str,
    monitors: list[MonitorState],
    elements: list[UIElementState],
) -> float:
    score = 0.2
    if hwnd:
        score += 0.35
    if title:
        score += 0.15
    if monitors:
        score += 0.2
    if elements:
        score += 0.1
    return min(1.0, score)


def _browser_name(app: str) -> str:
    low = (app or "").lower()
    for b in ("chrome", "edge", "firefox", "opera", "brave"):
        if b in low:
            return b
    return ""


def _page_type(url: str) -> str:
    u = (url or "").lower()
    if not u:
        return ""
    if "youtube.com/watch" in u or "youtu.be/" in u:
        return "watch"
    if "youtube.com/results" in u or "search_query=" in u:
        return "search"
    if "youtube.com" in u:
        return "home"
    return "unknown"


def _as_int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
