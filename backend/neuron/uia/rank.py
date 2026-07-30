"""Rank UI Automation candidates for a semantic query (e.g. 'Settings')."""

from __future__ import annotations

import re
from typing import Iterable

from neuron.uia.types import CLICK_PREFERRED, TYPE_ALIASES, ElementInfo


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def resolve_type_filter(control_type: str | None) -> set[str] | None:
    if not control_type:
        return None
    key = _norm(control_type).replace(" ", "")
    if key in TYPE_ALIASES:
        return set(TYPE_ALIASES[key])
    # Allow raw ControlTypeName
    raw = control_type if control_type.endswith("Control") else control_type + "Control"
    return {raw, control_type}


def score_element(
    el: ElementInfo,
    query: str,
    *,
    prefer_clickable: bool = True,
    type_filter: set[str] | None = None,
) -> float:
    q = _norm(query)
    if not q:
        return 0.0

    name = _norm(el.name)
    aid = _norm(el.automation_id)
    help_t = _norm(el.help_text)
    value = _norm(el.value)
    ctype = el.control_type or ""

    if type_filter and ctype not in type_filter:
        return -1000.0
    if el.offscreen:
        return -500.0
    if not el.enabled:
        score_base = -5.0
    else:
        score_base = 0.0

    score = score_base

    # Name / AutomationId / help matching
    if name == q or aid == q:
        score += 100.0
    elif name.startswith(q) or aid.startswith(q):
        score += 70.0
    elif q in name or q in aid:
        score += 50.0
    elif help_t and (q in help_t or help_t == q):
        score += 35.0
    elif value and q in value:
        score += 25.0
    else:
        # Token overlap (e.g. "open settings" vs "Settings")
        q_tokens = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 3]
        hay = f"{name} {aid} {help_t}"
        hits = sum(1 for t in q_tokens if t in hay)
        if hits:
            score += 15.0 * hits
        else:
            return -1.0  # no semantic match

    # Prefer interactive types for click goals
    if prefer_clickable:
        if ctype in CLICK_PREFERRED:
            score += 20.0
        elif ctype in ("TextControl", "PaneControl", "GroupControl", "ThumbControl"):
            score -= 10.0

    # Prefer visible, reasonably sized targets
    if el.width >= 8 and el.height >= 8:
        score += 5.0
    if el.width > 1200 and el.height > 800 and ctype in ("PaneControl", "WindowControl"):
        score -= 15.0  # giant panes are rarely the click target

    # Prefer shallower chrome (menus/tabs near top of tree)
    score += max(0.0, 8.0 - float(el.depth))

    # Slight boost if path suggests nav chrome
    path_l = _norm(el.path)
    if any(x in path_l for x in ("menu", "nav", "ribbon", "toolbar", "tab")):
        score += 4.0

    return score


def rank_candidates(
    elements: Iterable[ElementInfo],
    query: str,
    *,
    control_type: str | None = None,
    prefer_clickable: bool = True,
    limit: int = 10,
) -> list[ElementInfo]:
    type_filter = resolve_type_filter(control_type)
    scored: list[ElementInfo] = []
    for el in elements:
        s = score_element(
            el, query, prefer_clickable=prefer_clickable, type_filter=type_filter
        )
        if s < 0:
            continue
        el.score = s
        scored.append(el)
    scored.sort(key=lambda e: (-e.score, e.depth, -e.width * e.height))
    return scored[:limit]
