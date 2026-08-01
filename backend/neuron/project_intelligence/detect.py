"""Detect Project Intelligence intents — never steal Category A FastIntent."""

from __future__ import annotations

import re
from typing import Any

from neuron.project_intelligence.types import PICapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_PI = re.compile(
    r"("
    r"what does (this|the) project do|where is authenticat\w*|find memory leaks?|"
    r"project (intelligence|graph|map|architecture)|codebase (map|graph)|"
    r"architecture (map|overview|of)|module (graph|map|relationships?)|"
    r"remember (this )?project|index (all )?(folders|source|assets)|"
    r"project overview|explain (this|the) (codebase|project structure)|"
    r"where is (the )?(auth|login|oauth|jwt)|memory leak|"
    r"generate (a )?project graph|understand (every|this) project"
    r")",
    re.I,
)


def looks_like_project_intelligence(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("project intel") or low in ("project intelligence", "pi status"):
        return True
    return bool(_PI.search(t))


def classify_pi_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if "pi status" in low or low in ("project intelligence", "project intel status"):
        return {"capability": PICapability.STATUS.value, "args": {}}

    if re.search(r"\bwhat does (this|the) project do\b", low) or "project overview" in low:
        return {"capability": PICapability.OVERVIEW.value, "args": {}}

    if re.search(r"\b(find )?memory leaks?\b", low):
        return {"capability": PICapability.LEAKS.value, "args": {}}

    if re.search(r"\bwhere is (the )?(auth|authenticat|login|oauth|jwt)\b", low) or "where is authentication" in low:
        return {"capability": PICapability.LOCATE.value, "args": {"topic": "authentication"}}

    if re.search(r"\bwhere is\b", low):
        m = re.search(r"where is (?:the )?(.+?)(?:\?|$)", low)
        topic = (m.group(1).strip() if m else "feature").rstrip(".")
        return {"capability": PICapability.LOCATE.value, "args": {"topic": topic}}

    if re.search(r"\b(project graph|codebase (map|graph)|generate (a )?project graph|module (graph|map))\b", low):
        return {"capability": PICapability.GRAPH.value, "args": {}}

    if re.search(r"\b(architecture|module relationships|remember (this )?project)\b", low):
        return {"capability": PICapability.ARCHITECTURE.value, "args": {}}

    if re.search(r"\b(index (all )?(folders|source|assets)|understand (every|this) project)\b", low):
        return {"capability": PICapability.INDEX.value, "args": {}}

    if re.search(r"\bfind\b", low) and "leak" not in low:
        m = re.search(r"find\s+(.+)$", low)
        return {"capability": PICapability.SEARCH.value, "args": {"query": (m.group(1) if m else t).strip(" ?.!")}}

    return {"capability": PICapability.OVERVIEW.value, "args": {}}
