"""V3.4 ElementResolver — semantic UI targeting before coordinates.

Handles phrases such as:
  first video / second result / search box / settings button /
  blue button / Blender window

Uses PerceptionEngine observations (semantics) first, then composes the
existing V2 neuron.brain.element_resolver cascade (DOM → UIA → OCR →
vision → coords). Does not redesign the planner.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from neuron.v3.perception_types import Observation, PerceivedElement

_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
    "previous": -2,
}

_COLORS = (
    "blue", "red", "green", "yellow", "orange", "purple", "pink",
    "white", "black", "gray", "grey", "brown",
)

_ROLE_ALIASES = {
    "video": "video",
    "videos": "video",
    "result": "browser_result",
    "results": "browser_result",
    "button": "button",
    "btn": "button",
    "link": "link",
    "tab": "tab",
    "tabs": "tab",
    "window": "window",
    "windows": "window",
    "menu": "menu_item",
    "menuitem": "menu_item",
    "menu item": "menu_item",
    "file": "file",
    "search box": "text_field",
    "searchbox": "text_field",
    "search field": "text_field",
    "text field": "text_field",
    "textbox": "text_field",
    "input": "text_field",
}


@dataclass
class ElementHit:
    """Result of resolving a natural-language element query."""

    query: str
    element: PerceivedElement | None = None
    confidence: float = 0.0
    evidence: str = ""
    needs_clarification: bool = False
    clarification_prompt: str = ""
    candidates: list[str] = field(default_factory=list)
    action_hint: str = ""  # click | focus | play_result | activate_window
    args_hint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.element is not None:
            d["element"] = self.element.to_dict()
        return d


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _parse_ordinal(text: str) -> tuple[str | None, int | None]:
    m = re.search(
        r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|previous)\b",
        text,
        re.I,
    )
    if not m:
        return None, None
    word = m.group(1).lower()
    return word, _ORDINALS.get(word)


def _parse_color(text: str) -> str | None:
    m = re.search(r"\b(" + "|".join(_COLORS) + r")\b", text, re.I)
    return m.group(1).lower() if m else None


def _parse_role(text: str) -> str | None:
    t = _norm(text)
    # Longer phrases first
    for phrase in (
        "search box", "search field", "text field", "menu item",
    ):
        if phrase in t:
            return _ROLE_ALIASES[phrase]
    m = re.search(
        r"\b(videos?|results?|buttons?|links?|tabs?|windows?|menus?|files?|"
        r"searchbox|textbox|input)\b",
        t,
        re.I,
    )
    if not m:
        return None
    key = m.group(1).lower().rstrip("s")
    if m.group(1).lower() in ("videos", "results", "buttons", "links", "tabs", "windows", "menus", "files"):
        key = m.group(1).lower()
    return _ROLE_ALIASES.get(key) or _ROLE_ALIASES.get(key.rstrip("s"))


def _name_tokens(text: str, role: str | None, color: str | None) -> str:
    """Strip structural words; leftover is the semantic name (e.g. Settings, Blender)."""
    t = _norm(text)
    drop = {
        "the", "a", "an", "my", "please", "click", "press", "open", "focus",
        "select", "play", "find", "go", "to", "on", "one", "that", "this",
        "first", "second", "third", "fourth", "fifth", "1st", "2nd", "3rd",
        "4th", "5th", "last", "previous",
    }
    if color:
        drop.add(color)
    for phrase, r in _ROLE_ALIASES.items():
        if role and r == role:
            t = t.replace(phrase, " ")
    # also strip bare role words
    for w in (
        "video", "videos", "result", "results", "button", "buttons", "link",
        "links", "tab", "tabs", "window", "windows", "menu", "file", "files",
        "box", "field",
    ):
        t = re.sub(rf"\b{w}\b", " ", t)
    tokens = [x for x in t.split() if x not in drop]
    return " ".join(tokens).strip()


def _pick_ordinal(items: list[PerceivedElement], index: int | None) -> PerceivedElement | None:
    if not items or index is None:
        return None
    if index == -1:
        return items[-1]
    if index == -2:
        return items[-2] if len(items) >= 2 else None
    if 1 <= index <= len(items):
        return items[index - 1]
    return None


def _score_name(query_name: str, el_name: str) -> float:
    q = _norm(query_name)
    n = _norm(el_name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if n.startswith(q) or q.startswith(n):
        return 0.85
    if q in n or n in q:
        return 0.7
    qtoks = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 2]
    if not qtoks:
        return 0.0
    hits = sum(1 for t in qtoks if t in n)
    return 0.55 * (hits / len(qtoks)) if hits else 0.0


class ElementResolver:
    """Resolve NL element queries against an Observation (semantics first)."""

    def resolve(
        self,
        query: str,
        *,
        observation: Observation | None = None,
        perceive: bool = False,
        allow_ocr: bool = False,
        allow_vision: bool = False,
    ) -> ElementHit:
        q = (query or "").strip()
        if not q:
            return ElementHit(query="", confidence=0.0, evidence="empty")

        obs = observation
        if obs is None and perceive:
            from neuron.v3.perception_engine import observe
            obs = observe(q, allow_ocr=allow_ocr, allow_vision=allow_vision)

        if obs is not None:
            hit = self.resolve_against(q, obs)
            if hit.element is not None or hit.needs_clarification:
                return hit

        # Fall through: compose V2 cascade for a concrete label
        return self._fallback_v2(q)

    def resolve_against(self, query: str, observation: Observation) -> ElementHit:
        q = (query or "").strip()
        ord_word, ord_idx = _parse_ordinal(q)
        color = _parse_color(q)
        role = _parse_role(q)
        name = _name_tokens(q, role, color)

        pool = list(observation.elements)

        # Role filter
        if role:
            role_pool = [e for e in pool if e.role == role]
            # browser_result also accepts video/link
            if not role_pool and role == "browser_result":
                role_pool = [
                    e for e in pool if e.role in ("browser_result", "video", "link", "list_item")
                ]
            if role_pool:
                pool = role_pool

        # Color filter (meta.color / name contains color)
        if color:
            colored = [
                e
                for e in pool
                if _norm(str((e.meta or {}).get("color") or "")) == color
                or color in _norm(e.name)
            ]
            if colored:
                pool = colored
            elif not name:
                # Asked for color+role but no match — clarify rather than guess coords
                labels = [e.name for e in observation.by_role(role or "button") if e.name][:6]
                return ElementHit(
                    query=q,
                    needs_clarification=True,
                    clarification_prompt=(
                        f"I don't see a {color} {role or 'element'}. "
                        + ("Options: " + "; ".join(labels) if labels else "Which one?")
                    ),
                    candidates=labels,
                    confidence=0.3,
                    evidence="color_not_found",
                )

        # Ordinal selection among filtered pool
        if ord_idx is not None and pool:
            chosen = _pick_ordinal(pool, ord_idx)
            if chosen is None:
                labels = [e.name for e in pool if e.name][:8]
                return ElementHit(
                    query=q,
                    needs_clarification=True,
                    clarification_prompt=(
                        f"Which is the {ord_word}? "
                        + "; ".join(f"{i+1}. {l}" for i, l in enumerate(labels[:6]))
                    ),
                    candidates=labels,
                    confidence=0.35,
                    evidence="ordinal_out_of_range",
                )
            return self._hit_from_element(
                q, chosen, confidence=0.92, evidence=f"ordinal:{ord_word}"
            )

        # Name / semantic match
        if name and pool:
            scored: list[tuple[float, PerceivedElement]] = []
            for e in pool:
                s = _score_name(name, e.name)
                # Window titles often "Blender - file.blend" / process Blender
                if role == "window" or (not role and "window" in _norm(q)):
                    s = max(s, _score_name(name, e.application or ""))
                if s >= 0.55:
                    scored.append((s * (0.5 + 0.5 * e.confidence), e))
            scored.sort(key=lambda x: -x[0])
            if scored:
                best_s, best = scored[0]
                # Ambiguous top-2
                if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.05:
                    labels = [e.name for _, e in scored[:5]]
                    return ElementHit(
                        query=q,
                        needs_clarification=True,
                        clarification_prompt="Which one? " + "; ".join(labels),
                        candidates=labels,
                        confidence=0.4,
                        evidence="ambiguous_name",
                    )
                return self._hit_from_element(
                    q, best, confidence=min(0.95, best_s), evidence="name_match"
                )

        # Role-only (e.g. "search box") — prefer search-ish text_field
        if role and pool and not name and ord_idx is None:
            if role == "text_field":
                searchish = [
                    e
                    for e in pool
                    if "search" in _norm(e.name) or "search" in _norm(str((e.meta or {}).get("role") or ""))
                ]
                pick = searchish[0] if searchish else pool[0]
            else:
                pick = pool[0]
            return self._hit_from_element(
                q, pick, confidence=0.75, evidence="role_only"
            )

        labels = [e.name for e in observation.elements if e.name][:8]
        return ElementHit(
            query=q,
            confidence=0.2,
            evidence="unresolved_observation",
            candidates=labels,
            needs_clarification=bool(labels) and bool(ord_idx or name),
            clarification_prompt=(
                "Which element? " + "; ".join(labels) if labels and (ord_idx or name) else ""
            ),
        )

    def _hit_from_element(
        self,
        query: str,
        el: PerceivedElement,
        *,
        confidence: float,
        evidence: str,
    ) -> ElementHit:
        action = "click"
        args: dict[str, Any] = {"name": el.name}
        if el.role == "video" or el.role == "browser_result":
            action = "play_result"
            if el.index is not None:
                args = {"index": el.index}
        elif el.role == "window":
            action = "activate_window"
            args = {"title": el.name, "name": el.name}
        elif el.role == "text_field":
            action = "focus"
            args = {"name": el.name, "role": "text_field"}
        if el.meta.get("center_x") is not None:
            args.setdefault("x", el.meta["center_x"])
            args.setdefault("y", el.meta["center_y"])
        if el.bounds and "center_x" in el.bounds:
            args.setdefault("x", el.bounds["center_x"])
            args.setdefault("y", el.bounds["center_y"])
        return ElementHit(
            query=query,
            element=el,
            confidence=confidence,
            evidence=evidence,
            action_hint=action,
            args_hint=args,
            candidates=[el.name] if el.name else [],
        )

    def _fallback_v2(self, query: str) -> ElementHit:
        """Compose existing brain.element_resolver.find — no planner change."""
        try:
            from neuron.brain import element_resolver as v2
            # Strip ordinal/role fluff for V2 name search
            role = _parse_role(query)
            color = _parse_color(query)
            name = _name_tokens(query, role, color) or query
            result = v2.find({
                "name": name,
                "control_type": role or "",
                "allow_ocr": True,
            })
            if not result.success:
                return ElementHit(
                    query=query,
                    confidence=0.15,
                    evidence="v2_unresolved",
                    clarification_prompt=result.error or f"Couldn't find {query}",
                    needs_clarification=True,
                )
            resolved = (result.state or {}).get("resolved") or {}
            el = PerceivedElement(
                id=f"v2:{resolved.get('source', 'x')}",
                role=role or "other",
                name=resolved.get("name") or name,
                source=resolved.get("source") or "uia",
                confidence=float(resolved.get("confidence") or 0.6),
                interactive=True,
                clickable=True,
                bounds={
                    "center_x": int(resolved.get("x") or 0),
                    "center_y": int(resolved.get("y") or 0),
                },
                meta=dict(resolved.get("element") or {}),
            )
            return self._hit_from_element(
                query, el, confidence=el.confidence, evidence=f"v2:{el.source}"
            )
        except Exception as exc:
            return ElementHit(
                query=query,
                confidence=0.0,
                evidence=f"v2_error:{exc}",
                needs_clarification=True,
                clarification_prompt=f"Couldn't resolve {query}",
            )


def resolve_element(
    query: str,
    *,
    observation: Observation | None = None,
    perceive: bool = False,
    **kwargs: Any,
) -> ElementHit:
    return ElementResolver().resolve(
        query, observation=observation, perceive=perceive, **kwargs
    )
