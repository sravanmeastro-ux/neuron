"""Entity extraction — apps, sites, queries, monitors, ordinals."""

from __future__ import annotations

import re

from neuron.understand.synonyms import canonicalize_app, canonicalize_site
from neuron.understand.types import EntitySpan

_SITES = (
    "youtube", "yt", "google", "gmail", "github", "netflix", "reddit",
    "twitter", "facebook", "instagram", "spotify", "discord",
)

_KNOWN_APPS = (
    "chrome", "edge", "firefox", "brave", "notepad", "blender", "steam",
    "discord", "spotify", "vscode", "code", "cursor", "explorer", "calculator",
    "word", "excel", "powerpoint", "unreal engine", "roblox studio", "roblox",
    "browser", "paint", "settings", "terminal", "powershell",
)

_MONITOR_RE = re.compile(
    r"\b(?:monitor|screen|display)\s*(?:number\s*)?"
    r"(?P<num>\d+|one|two|three|four|five|first|second|third|left|right|main|other)\b",
    re.I,
)

_ORDINAL_RE = re.compile(
    r"\b(?:the\s+)?(?P<ord>first|second|third|1st|2nd|3rd|last|next)\b",
    re.I,
)

_WORD_NUM = {
    "one": "1", "first": "1", "1st": "1",
    "two": "2", "second": "2", "2nd": "2",
    "three": "3", "third": "3", "3rd": "3",
    "four": "4", "five": "5",
    "left": "left", "right": "right", "main": "main", "other": "other",
}


def extract_entities(text: str) -> list[EntitySpan]:
    t = (text or "").strip()
    low = t.lower()
    out: list[EntitySpan] = []

    m = _MONITOR_RE.search(low)
    if m:
        raw_num = m.group("num").lower()
        out.append(EntitySpan(
            kind="monitor",
            value=_WORD_NUM.get(raw_num, raw_num),
            raw=m.group(0),
            confidence=0.95,
        ))

    om = _ORDINAL_RE.search(low)
    if om:
        out.append(EntitySpan(
            kind="ordinal",
            value=om.group("ord").lower(),
            raw=om.group(0),
            confidence=0.9,
        ))

    sm = re.search(
        rf"\b(?:search|find|look\s+up)\s+(?:on\s+)?({'|'.join(_SITES)})\s+(?:for\s+)?(.+)$",
        low,
    )
    if not sm:
        sm = re.search(
            rf"\b(?:on|in)\s+({'|'.join(_SITES)})\s+(?:search|find)\s+(?:for\s+)?(.+)$",
            low,
        )
    if sm:
        site = canonicalize_site(sm.group(1))
        query = sm.group(2).strip(" .,!?")
        out.append(EntitySpan(kind="website", value=site, raw=sm.group(1), confidence=0.95))
        if query:
            out.append(EntitySpan(kind="query", value=query, raw=query, confidence=0.9))
        return out

    # Site mention
    for site in _SITES:
        if re.search(rf"\b{re.escape(site)}\b", low):
            if re.search(r"\b(?:search|find|look)\b", low):
                qm = re.search(
                    r"\b(?:search|find|look\s+up|look\s+for)\s+(?:for\s+)?(.+)$", low
                )
                if qm:
                    q = qm.group(1).strip()
                    q = re.sub(
                        rf"^(?:on\s+)?{re.escape(site)}\s+(?:for\s+)?", "", q
                    ).strip()
                    out.append(EntitySpan(
                        kind="website",
                        value=canonicalize_site(site),
                        raw=site,
                        confidence=0.85,
                    ))
                    if q:
                        out.append(EntitySpan(
                            kind="query", value=q, raw=q, confidence=0.85
                        ))
                    return out
            out.append(EntitySpan(
                kind="website",
                value=canonicalize_site(site),
                raw=site,
                confidence=0.92,
            ))
            break

    qm = re.search(
        r"\b(?:search|find|look\s+up|look\s+for)\s+(?:for\s+)?(.+)$", low
    )
    if qm and not any(e.kind == "query" for e in out):
        q = qm.group(1).strip(" .,!?")
        if q and not re.match(r"^(?:chrome|edge|blender|notepad)\b", q):
            out.append(EntitySpan(kind="query", value=q, raw=q, confidence=0.88))

    am = re.search(
        r"\b(?:open|launch|start|run|close|quit|focus|switch\s+to|move)\s+"
        r"(?:the\s+|my\s+|a\s+)?"
        r"(.+?)(?:\s+to\s+monitor|\s+on\s+monitor|$)",
        low,
    )
    if am:
        name = canonicalize_app(am.group(1))
        name = re.sub(r"\b(?:please|now|for\s+me)\b", "", name).strip()
        if name and name not in ("it", "that", "this", "them"):
            if name in _SITES or name in ("youtube", "google", "gmail", "github", "netflix"):
                if not any(e.kind == "website" for e in out):
                    out.append(EntitySpan(
                        kind="website",
                        value=canonicalize_site(name),
                        raw=name,
                        confidence=0.9,
                    ))
            else:
                out.append(EntitySpan(
                    kind="application",
                    value=name,
                    raw=am.group(1),
                    confidence=0.9,
                ))

    if not any(e.kind == "application" for e in out):
        for app in sorted(_KNOWN_APPS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(app)}\b", low):
                out.append(EntitySpan(
                    kind="application",
                    value=canonicalize_app(app),
                    raw=app,
                    confidence=0.75,
                ))
                break

    return out
