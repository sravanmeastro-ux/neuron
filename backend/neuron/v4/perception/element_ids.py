"""Stable / best-effort UI element identity for V4.2 (resolver comes in V4.3)."""

from __future__ import annotations

import hashlib
import re
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())[:80]


def _round_bounds(bounds: dict[str, Any] | None, quant: int = 8) -> str:
    if not bounds:
        return ""
    parts = []
    for k in ("left", "top", "width", "height", "center_x", "center_y"):
        if k in bounds and bounds[k] is not None:
            try:
                parts.append(f"{k}:{int(bounds[k]) // quant * quant}")
            except (TypeError, ValueError):
                pass
    return ",".join(parts)


def stable_element_id(
    *,
    application: str = "",
    window: str = "",
    window_hwnd: int = 0,
    automation_id: str = "",
    role: str = "",
    name: str = "",
    hierarchy: str = "",
    bounds: dict[str, Any] | None = None,
    source: str = "",
) -> tuple[str, float]:
    """
    Return (element_id, identity_confidence).

    Prefer semantic attributes over list indexes.
    Confidence reflects how deterministic the ID is (0..1).
    """
    aid = _norm(automation_id)
    role_n = _norm(role).replace("control", "")
    name_n = _norm(name)
    hier = _norm(hierarchy)
    app = _norm(application)
    win = _norm(window)[:40]
    bq = _round_bounds(bounds)

    strong: list[str] = []
    weak: list[str] = []
    conf = 0.15

    if window_hwnd:
        strong.append(f"hwnd:{int(window_hwnd)}")
        conf += 0.15
    if app:
        strong.append(f"app:{app}")
        conf += 0.1
    if aid:
        strong.append(f"aid:{aid}")
        conf += 0.35
    if role_n:
        strong.append(f"role:{role_n}")
        conf += 0.1
    if name_n:
        strong.append(f"name:{name_n}")
        conf += 0.15
    if hier:
        strong.append(f"path:{hier}")
        conf += 0.1
    if bq:
        weak.append(f"box:{bq}")
        conf += 0.05 if aid or name_n else 0.12
    if source:
        weak.append(f"src:{_norm(source)}")

    if not strong and not weak:
        # Last resort — unstable random-ish from empty; mark very low confidence
        raw = f"empty|{time_bucket()}"
        return "el:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12], 0.05

    material = "|".join(strong + ([win] if win else []) + weak)
    digest = hashlib.sha1(material.encode("utf-8", "replace")).hexdigest()[:16]
    # Prefix helps humans/debug; not used as sole identity
    prefix = aid[:12] if aid else (role_n[:8] or "el")
    return f"{prefix}:{digest}", min(1.0, conf)


def time_bucket() -> str:
    import time
    return str(int(time.time() // 60))


def element_fingerprint_changed(id_a: str, id_b: str) -> bool:
    return (id_a or "") != (id_b or "")


def normalize_uia_role(control_type: str, name: str = "") -> str:
    c = (control_type or "").lower()
    n = _norm(name)
    if "button" in c or "splitbutton" in c:
        return "button"
    if "hyperlink" in c or "link" in c:
        return "link"
    if "edit" in c or "document" in c:
        return "text_field"
    if "menuitem" in c or ("menu" in c and "bar" not in c):
        return "menu_item"
    if "tabitem" in c or (c.endswith("tab") and "table" not in c):
        return "tab"
    if "window" in c:
        return "window"
    if "listitem" in c:
        return "list_item"
    if "checkbox" in c:
        return "checkbox"
    if "search" in n and ("edit" in c or "combo" in c):
        return "text_field"
    return "other"


def looks_sensitive_element(*, name: str = "", automation_id: str = "", role: str = "") -> bool:
    blob = f"{name} {automation_id} {role}".lower()
    return any(
        s in blob
        for s in (
            "password", "passwd", "pin", "cvv", "ssn", "secret",
            "credit card", "card number", "api key",
        )
    )
