"""Text / bbox / icon matching with confidence scoring."""

from __future__ import annotations

import re
from typing import Any

from neuron.screen.ground import score_candidate
from neuron.screen.types import ScreenElement, ScreenSnapshot
from neuron.ui_grounding.detect_ui import icon_candidates
from neuron.ui_grounding.types import GroundMatch


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def text_match_score(el: ScreenElement, query: str) -> float:
    """0..1 text similarity."""
    q = _norm(query)
    name = _norm(el.name)
    if not q or not name:
        return 0.0
    if name == q:
        return 1.0
    if q in name or name in q:
        return 0.85
    qt, nt = set(q.split()), set(name.split())
    if not qt:
        return 0.0
    return len(qt & nt) / len(qt)


def bbox_match_score(el: ScreenElement, *, hint_bbox: list[int] | None = None) -> float:
    """Score geometric plausibility / optional bbox overlap (IoU)."""
    if not el.width or not el.height:
        return 0.2
    area = el.width * el.height
    geo = 0.5
    if 20 <= area <= 400_000:
        geo = 0.85
    if 400 <= area <= 80_000:
        geo = 1.0
    if not hint_bbox or len(hint_bbox) != 4:
        return geo
    # IoU with hint
    a = (el.left, el.top, el.right, el.bottom)
    b = (int(hint_bbox[0]), int(hint_bbox[1]), int(hint_bbox[2]), int(hint_bbox[3]))
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return geo * 0.3
    union = max(1, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    iou = inter / union
    return 0.4 * geo + 0.6 * iou


def icon_match_score(el: ScreenElement, query: str) -> float:
    q = _norm(query)
    if "icon" not in q and el.role != "icon" and not (el.meta or {}).get("iconish"):
        return 0.0
    # Name tokens that often accompany icons
    base = 0.55 if el.role == "icon" or (el.meta or {}).get("iconish") else 0.2
    ts = text_match_score(el, query)
    return min(1.0, base + 0.45 * ts)


def confidence_score(
    el: ScreenElement,
    query: str,
    *,
    snap: ScreenSnapshot | None = None,
    hint_bbox: list[int] | None = None,
) -> tuple[float, dict[str, float]]:
    """Composite 0..1 confidence from text + bbox + icon + screen.ground score."""
    t = text_match_score(el, query)
    b = bbox_match_score(el, hint_bbox=hint_bbox)
    i = icon_match_score(el, query)
    legacy = score_candidate(el, query, snap=snap)
    # normalize legacy (~0-150) softly
    legacy_n = max(0.0, min(1.0, legacy / 120.0))
    # Weighted blend
    conf = 0.45 * t + 0.20 * b + 0.15 * i + 0.20 * legacy_n
    conf = conf * (0.5 + 0.5 * float(el.confidence or 0.8))
    if not el.enabled:
        conf *= 0.5
    return conf, {"text": t, "bbox": b, "icon": i, "legacy": legacy_n, "raw_legacy": legacy}


def ground_target(
    query: str,
    snap: ScreenSnapshot,
    *,
    hint_bbox: list[int] | None = None,
    role_hint: str = "",
    min_confidence: float = 0.35,
) -> GroundMatch | None:
    cands = list(snap.elements)
    # include iconish
    for ic in icon_candidates(snap):
        if all(ic.id != e.id for e in cands):
            cands.append(ic)
    if role_hint:
        filtered = [e for e in cands if e.role == role_hint or role_hint in (e.role or "")]
        if filtered:
            cands = filtered

    best: tuple[float, ScreenElement, dict[str, float]] | None = None
    for el in cands:
        conf, parts = confidence_score(el, query, snap=snap, hint_bbox=hint_bbox)
        if best is None or conf > best[0]:
            best = (conf, el, parts)

    if not best or best[0] < min_confidence:
        return None
    conf, el, parts = best
    return GroundMatch(
        id=el.id,
        name=el.name,
        role=el.role,
        source=el.source,
        x=el.center[0],
        y=el.center[1],
        bbox=[el.left, el.top, el.right, el.bottom],
        confidence=round(conf, 4),
        text_score=round(parts["text"], 4),
        bbox_score=round(parts["bbox"], 4),
        icon_score=round(parts["icon"], 4),
        reason=f"text={parts['text']:.2f} bbox={parts['bbox']:.2f} icon={parts['icon']:.2f}",
    )


def match_near_point(snap: ScreenSnapshot, x: int, y: int, *, radius: int = 48) -> GroundMatch | None:
    """Ground a coordinate click by finding a nearby detected element (never assume empty space is a control)."""
    best = None
    best_d = 1e18
    for el in snap.elements:
        cx, cy = el.center
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < best_d:
            best_d = d
            best = el
    if not best or best_d > radius * radius:
        return None
    conf, parts = confidence_score(best, best.name or "target", snap=snap)
    return GroundMatch(
        id=best.id,
        name=best.name,
        role=best.role,
        source=best.source,
        x=best.center[0],
        y=best.center[1],
        bbox=[best.left, best.top, best.right, best.bottom],
        confidence=round(max(conf, 0.4), 4),
        text_score=round(parts["text"], 4),
        bbox_score=round(parts["bbox"], 4),
        icon_score=round(parts["icon"], 4),
        reason=f"near_point d2={best_d}",
    )
