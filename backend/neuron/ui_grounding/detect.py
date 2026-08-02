"""Detect UI grounding intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.ui_grounding.types import UGCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_UG = re.compile(
    r"("
    r"ui grounding|ground (the |and )?click|grounded click|"
    r"click (the )?.{2,40} (button|tab|icon|menu|link)|"
    r"visually (click|verify|ground)|find (the )?button|"
    r"observe (the )?screen (then|and) click|verify (the )?click"
    r")",
    re.I,
)


def looks_like_ui_grounding(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("ground ") or "ui grounding" in low:
        return True
    # Don't steal bare "Open Chrome"
    if re.match(r"^open\s+\w+$", low):
        return False
    return bool(_UG.search(t))


def classify_ug_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if "ui grounding" in low or low in ("grounding status", "ui grounding status"):
        return {"capability": UGCapability.STATUS.value, "args": {}}

    if re.search(r"\bobserve (the )?screen\b", low) and "click" not in low:
        return {"capability": UGCapability.OBSERVE.value, "args": {}}

    m = re.search(r"\bground(?:ed)?(?:\s+and)?\s+click\s+(.+)$", low)
    if m:
        return {"capability": UGCapability.CLICK.value, "args": {"target": m.group(1).strip(" .")}}

    m = re.search(r"\bclick (?:the )?(.+?)(?:\s+button|\s+tab|\s+icon|\s+menu|\s+link)?$", low)
    if m and looks_like_ui_grounding(t):
        return {"capability": UGCapability.CLICK.value, "args": {"target": m.group(1).strip(" .")}}

    m = re.search(r"\bground\s+(.+)$", low)
    if m:
        return {"capability": UGCapability.GROUND.value, "args": {"target": m.group(1).strip(" .")}}

    return {"capability": UGCapability.PIPELINE.value, "args": {"target": t}}
