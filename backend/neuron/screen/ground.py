"""Visual grounding — pick best UI element among matches."""

from __future__ import annotations

import re
from typing import Iterable

from neuron.screen import context as screen_ctx
from neuron.screen.types import GroundedTarget, ScreenElement, ScreenSnapshot

_COLOR_WORDS = {
    "blue", "red", "green", "yellow", "orange", "purple", "white", "black",
    "gray", "grey", "pink",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _role_bonus(el: ScreenElement, query: str) -> float:
    q = _norm(query)
    role = el.role
    score = 0.0
    if "button" in q and role == "button":
        score += 25
    if "tab" in q and role == "tab":
        score += 30
    if "checkbox" in q and role == "checkbox":
        score += 25
    if "menu" in q and role in ("menu", "menuitem"):
        score += 25
    if "field" in q or "input" in q or "textbox" in q:
        if role == "edit":
            score += 25
    if "download" in q and role == "button":
        score += 10
    if "login" in q and role == "button":
        score += 10
    if "popup" in q or "close" in q:
        if role == "button" and any(k in _norm(el.name) for k in ("close", "x", "dismiss", "cancel", "ok")):
            score += 20
    return score


def score_candidate(
    el: ScreenElement,
    query: str,
    *,
    snap: ScreenSnapshot | None = None,
) -> float:
    q = _norm(query)
    # Strip filler / color for name match
    q_name = q
    for c in _COLOR_WORDS:
        q_name = re.sub(rf"\b{c}\b", " ", q_name)
    q_name = re.sub(
        r"\b(the|a|an|button|tab|icon|menu|field|box|link|please|click|press|open)\b",
        " ",
        q_name,
    )
    q_name = re.sub(r"\s+", " ", q_name).strip()

    name = _norm(el.name)
    score = float(el.confidence) * 10.0

    if not el.enabled:
        score -= 15

    if q_name:
        if name == q_name:
            score += 100
        elif name.startswith(q_name) or q_name.startswith(name):
            score += 70
        elif q_name in name or name in q_name:
            score += 50
        else:
            # token overlap
            qt = set(q_name.split())
            nt = set(name.split())
            if qt and nt:
                score += 25.0 * len(qt & nt) / max(1, len(qt))

    score += _role_bonus(el, query)

    if el.focused:
        score += 15

    # Prefer larger clickable targets slightly
    area = el.width * el.height
    if 400 <= area <= 200_000:
        score += 5

    # Conversation / memory boost
    mem = screen_ctx.get_memory()
    if mem.last_click_name and _norm(mem.last_click_name) == name:
        score += 8
    if mem.focused_control and _norm(mem.focused_control) == name:
        score += 10

    # Color words: cannot detect color from UIA — slight penalty unless VLM used
    if any(c in q for c in _COLOR_WORDS) and el.source == "uia":
        score -= 5  # prefer OCR/VLM for color later

    # Prefer elements in the focused window center band
    if snap and snap.elements:
        ys = [e.y for e in snap.elements if e.y]
        if ys and el.y:
            mid = sorted(ys)[len(ys) // 2]
            if abs(el.y - mid) < 200:
                score += 3

    return score


def ground(
    query: str,
    snap: ScreenSnapshot,
    *,
    role_hint: str = "",
) -> GroundedTarget:
    """Return best matching element with alternatives."""
    q = (query or "").strip()
    cands = list(snap.elements)
    if role_hint:
        filtered = [e for e in cands if e.role == role_hint or role_hint in e.role]
        if filtered:
            cands = filtered

    scored: list[tuple[float, ScreenElement]] = []
    for el in cands:
        s = score_candidate(el, q, snap=snap)
        if s > 5:
            scored.append((s, el))
    scored.sort(key=lambda x: -x[0])

    if not scored:
        return GroundedTarget(query=q, score=0.0, reason="no_match")

    best_score, best = scored[0]
    alts = [e for _, e in scored[1:6]]
    reason = f"match name={best.name!r} role={best.role} src={best.source}"
    return GroundedTarget(
        element=best,
        query=q,
        score=best_score,
        reason=reason,
        alternatives=alts,
    )


def ordinal_pick(elements: Iterable[ScreenElement], ordinal: str) -> ScreenElement | None:
    items = [e for e in elements if e.role in ("tab", "listitem", "button", "link")]
    if not items:
        items = list(elements)
    # Left-to-right
    items = sorted(items, key=lambda e: (e.y // 40, e.x))
    key = (ordinal or "").lower()
    idx = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "last": -1}.get(key)
    if idx is None:
        return None
    if not items:
        return None
    return items[idx]
