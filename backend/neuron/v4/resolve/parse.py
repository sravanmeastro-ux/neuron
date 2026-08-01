"""Deterministic NL → ElementReference parsing (no LLM for ordinals/roles/spatial)."""

from __future__ import annotations

import re

from neuron.v4.resolve.roles import parse_role_from_text
from neuron.v4.resolve.types import ElementReference

_ORDINALS = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "number one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
}

_COLORS = (
    "blue", "red", "green", "yellow", "orange", "purple", "pink",
    "white", "black", "gray", "grey", "brown",
)

_SPATIAL = {
    "leftmost": "left",
    "left": "left",
    "rightmost": "right",
    "right": "right",
    "top": "top",
    "bottom": "bottom",
    "center": "center",
    "middle": "center",
    "top-left": "top_left",
    "top left": "top_left",
    "upper left": "top_left",
    "top-right": "top_right",
    "top right": "top_right",
    "upper right": "top_right",
    "bottom-left": "bottom_left",
    "bottom left": "bottom_left",
    "lower left": "bottom_left",
    "bottom-right": "bottom_right",
    "bottom right": "bottom_right",
    "lower right": "bottom_right",
}

_RELATIONS = (
    ("next to", "next_to"),
    ("beside", "next_to"),
    ("near", "near"),
    ("above", "above"),
    ("below", "below"),
    ("left of", "left_of"),
    ("right of", "right_of"),
)

_DEIXIS = re.compile(
    r"\b(it|that|this|this\s+one|that\s+one|there)\b",
    re.I,
)

_STOP = frozenset({
    "the", "a", "an", "please", "click", "press", "tap", "open", "select",
    "hit", "choose", "play", "on", "in", "at", "to", "for", "me", "my",
    "button", "buttons", "box", "field", "bar", "link", "links", "video",
    "videos", "result", "results", "tab", "tabs", "one", "ones",
})


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\"'`]", "", s)
    s = re.sub(r"[^\w\s\-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_reference(text: str) -> ElementReference:
    raw = (text or "").strip()
    t = _norm(raw)
    ref = ElementReference(raw=raw)

    if not t:
        return ref

    # Action hint
    if re.match(r"^(click|press|tap|hit)\b", t):
        ref.action_hint = "click"
    elif re.match(r"^play\b", t):
        ref.action_hint = "play"
    elif re.match(r"^(focus|select|choose)\b", t):
        ref.action_hint = "focus"

    # Deixis
    m = _DEIXIS.search(t)
    if m:
        d = _norm(m.group(1)).replace(" ", "_")
        ref.deixis = d

    # Ordinal
    m = re.search(
        r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|"
        r"number\s+one|one)\b",
        t,
        re.I,
    )
    if m:
        word = _norm(m.group(1))
        # avoid treating bare "one" in "this one" as ordinal when deixis present
        if word == "one" and ref.deixis:
            pass
        else:
            ref.ordinal_word = word
            ref.ordinal = _ORDINALS.get(word)

    # Color
    m = re.search(r"\b(" + "|".join(_COLORS) + r")\b", t)
    if m:
        ref.color = m.group(1).lower()

    # Spatial (prefer multi-word)
    for phrase, pos in sorted(_SPATIAL.items(), key=lambda x: -len(x[0])):
        if re.search(r"\b" + re.escape(phrase) + r"\b", t):
            ref.position = pos
            break

    # Relation + anchor: "button next to Settings"
    for phrase, rel in _RELATIONS:
        m = re.search(
            rf"\b{re.escape(phrase)}\s+(.+)$",
            t,
        )
        if m:
            ref.relation = rel
            anchor = _norm(m.group(1))
            # strip trailing role words from anchor
            anchor = re.sub(r"\b(button|link|tab|field|box)\b", "", anchor).strip()
            ref.relation_anchor = anchor
            break
        # "Settings button above Search"
        m = re.search(rf"^(.+?)\s+{re.escape(phrase)}\s+(.+)$", t)
        if m and not ref.relation:
            # prefer "X next to Y" where X is target descriptor already in name
            ref.relation = rel
            ref.relation_anchor = _norm(m.group(2))
            break

    # Role
    role = parse_role_from_text(t)
    if role:
        ref.role_hint = role
    # Special named controls already mapped via phrases in parse_role_from_text

    # Application / monitor hints
    m = re.search(r"\bin\s+(\w+)\b", t)
    if m and m.group(1) not in _STOP and m.group(1) not in ("the", "a"):
        # weak app hint
        cand = m.group(1)
        if cand in ("chrome", "edge", "firefox", "opera", "discord", "spotify", "blender", "youtube"):
            ref.application = cand
    m = re.search(r"\bon\s+monitor\s+(\d+)\b", t)
    if m:
        ref.monitor_id = int(m.group(1))

    # Name hint — remaining content words
    name = t
    for drop in (
        "click", "press", "tap", "hit", "play", "select", "choose", "open",
        "the", "a", "an", "please", "on", "in", "at", "to", "for",
        "first", "second", "third", "fourth", "fifth", "1st", "2nd", "3rd", "4th", "5th",
        "last", "left", "right", "top", "bottom", "center", "middle",
        "leftmost", "rightmost", "button", "buttons", "box", "field", "bar",
        "link", "links", "video", "videos", "result", "results", "tab", "tabs",
        "one", "ones", "this", "that", "it", "there", "search", "fullscreen",
        "full", "screen", "close", "minimize", "maximize", "pause", "play",
        "address", "url", "next", "beside", "near", "above", "below",
    ):
        name = re.sub(rf"\b{drop}\b", " ", name)
    for phrase, _ in _RELATIONS:
        name = name.replace(phrase, " ")
    if ref.relation_anchor:
        name = name.replace(ref.relation_anchor, " ")
    if ref.color:
        name = name.replace(ref.color, " ")
    if ref.application:
        name = name.replace(ref.application, " ")
    name = _norm(name)
    # Keep meaningful tokens
    toks = [w for w in name.split() if w not in _STOP and len(w) > 1]
    ref.name_hint = " ".join(toks)

    # If role is search_box and name empty, name_hint can stay empty (role-only)
    # If "Settings" style text-only
    if not ref.role_hint and not ref.deixis and ref.name_hint:
        # textual reference like "click Settings"
        pass

    return ref
