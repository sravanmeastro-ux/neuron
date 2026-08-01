"""UI element detection — fuse UIA + OCR into ScreenElement list."""

from __future__ import annotations

import time
from typing import Any

from neuron.screen.types import ScreenElement, ScreenSnapshot

_ROLE_MAP = {
    "ButtonControl": "button",
    "SplitButtonControl": "button",
    "HyperlinkControl": "link",
    "MenuItemControl": "menuitem",
    "MenuControl": "menu",
    "MenuBarControl": "menu",
    "EditControl": "edit",
    "DocumentControl": "edit",
    "CheckBoxControl": "checkbox",
    "RadioButtonControl": "checkbox",
    "ComboBoxControl": "dropdown",
    "TabItemControl": "tab",
    "TabControl": "tab",
    "ListItemControl": "listitem",
    "TreeItemControl": "listitem",
    "WindowControl": "window",
    "PaneControl": "window",
    "ImageControl": "icon",
    "TextControl": "text",
}


def _role_from_uia(ctype: str) -> str:
    return _ROLE_MAP.get(ctype or "", "other")


def detect_uia_elements(*, limit: int = 120) -> tuple[list[ScreenElement], dict[str, Any]]:
    """Walk foreground UIA tree → ScreenElements."""
    t0 = time.perf_counter()
    meta: dict[str, Any] = {}
    elements: list[ScreenElement] = []
    try:
        from neuron.uia.inspect import walk_elements, foreground_root
        root = foreground_root()
        if root is None:
            meta["error"] = "no_foreground"
            return [], meta
        infos = walk_elements(root, max_depth=6, limit=limit) or []
        for i, el in enumerate(infos):
            name = (getattr(el, "name", None) or "").strip()
            if not name and not getattr(el, "automation_id", ""):
                continue
            ctype = getattr(el, "control_type", "") or ""
            cx = int(getattr(el, "center_x", 0) or 0)
            cy = int(getattr(el, "center_y", 0) or 0)
            left = int(getattr(el, "left", 0) or 0)
            top = int(getattr(el, "top", 0) or 0)
            right = int(getattr(el, "right", 0) or 0)
            bottom = int(getattr(el, "bottom", 0) or 0)
            elements.append(ScreenElement(
                id=f"uia-{i}",
                name=name[:120] or str(getattr(el, "automation_id", "") or "")[:80],
                role=_role_from_uia(ctype),
                source="uia",
                x=cx,
                y=cy,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                width=max(0, right - left),
                height=max(0, bottom - top),
                confidence=0.9,
                enabled=bool(getattr(el, "enabled", True)),
                focused=False,
                meta={"control_type": ctype},
            ))
        meta["count"] = len(elements)
    except Exception as exc:
        meta["error"] = str(exc)
    meta["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return elements, meta


def detect_ocr_elements(image_path: str, *, limit: int = 80) -> tuple[list[ScreenElement], list[str], dict[str, Any]]:
    """OCR boxes → ScreenElements + text list."""
    t0 = time.perf_counter()
    meta: dict[str, Any] = {}
    elements: list[ScreenElement] = []
    texts: list[str] = []
    if not image_path:
        meta["error"] = "no_path"
        meta["ms"] = 0.0
        return elements, texts, meta
    try:
        from neuron.perception import ocr as ocr_mod
        res = ocr_mod.detect_text_regions({"path": image_path})
        regions = (res.state or {}).get("regions") or [] if res.success else []
        for i, r in enumerate(regions[:limit]):
            text = (r.get("text") or "").strip()
            if not text:
                continue
            texts.append(text)
            cx = int(r.get("center_x") or 0)
            cy = int(r.get("center_y") or 0)
            # Heuristic role from text
            role = "button" if len(text.split()) <= 3 else "text"
            low = text.lower()
            if any(k in low for k in ("login", "sign in", "submit", "download", "ok", "cancel", "close", "save", "next")):
                role = "button"
            elements.append(ScreenElement(
                id=f"ocr-{i}",
                name=text[:120],
                role=role,
                source="ocr",
                x=cx,
                y=cy,
                left=int(r.get("left") or 0),
                top=int(r.get("top") or 0),
                right=int(r.get("right") or 0),
                bottom=int(r.get("bottom") or 0),
                confidence=float(r.get("confidence") or 0.7),
                meta={},
            ))
        meta["count"] = len(elements)
    except Exception as exc:
        meta["error"] = str(exc)
    meta["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return elements, texts, meta


def build_snapshot(*, use_ocr: bool = True, use_uia: bool = True) -> ScreenSnapshot:
    """Screenshot + UIA + OCR fused snapshot."""
    import time as _time
    snap = ScreenSnapshot(ts=_time.time())
    timings: dict[str, float] = {}

    # Capture
    t0 = _time.perf_counter()
    path = ""
    try:
        from neuron.perception import capture_ops
        cap = capture_ops.get_active_window_screenshot({})
        if not cap.success:
            cap = capture_ops.capture_screen({})
        if cap.success:
            path = str((cap.state or {}).get("path") or "")
            snap.path = path
    except Exception as exc:
        timings["capture_error"] = 1.0
        _ = exc
    timings["screenshot_ms"] = round((_time.perf_counter() - t0) * 1000, 2)

    # Foreground app
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        snap.window_title = (fg.get("title") or "")[:160]
        snap.hwnd = int(fg.get("hwnd") or 0)
        low = snap.window_title.lower()
        for needle, app in (
            ("chrome", "chrome"), ("edge", "edge"), ("firefox", "firefox"),
            ("notepad", "notepad"), ("blender", "blender"), ("spotify", "spotify"),
            ("discord", "discord"), ("code", "vscode"), ("cursor", "cursor"),
        ):
            if needle in low:
                snap.application = app
                break
        if not snap.application:
            snap.application = (snap.window_title.split("-")[-1].strip() if snap.window_title else "")[:40]
    except Exception:
        pass

    elements: list[ScreenElement] = []
    if use_uia:
        uia_els, uia_meta = detect_uia_elements()
        elements.extend(uia_els)
        timings["uia_ms"] = float(uia_meta.get("ms") or 0)

    if use_ocr and path:
        ocr_els, texts, ocr_meta = detect_ocr_elements(path)
        snap.ocr_text = texts
        # Prefer UIA when names overlap; keep OCR-only extras
        uia_names = {e.name.lower() for e in elements if e.name}
        for e in ocr_els:
            if e.name.lower() not in uia_names:
                elements.append(e)
        timings["ocr_ms"] = float(ocr_meta.get("ms") or 0)

    # Taskbar heuristic: bottom 8% of primary-ish coords labeled
    for e in elements:
        if e.role == "other" and e.bottom > 0 and e.top > 900 and len(e.name) < 24:
            e.role = "taskbar"

    snap.elements = elements
    snap.timings_ms = timings
    return snap
