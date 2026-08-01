"""Map natural visual commands → ScreenPlan."""

from __future__ import annotations

import re

from neuron.screen.types import ScreenPlan

_VISUAL_HINT = re.compile(
    r"\b("
    r"click|press|tap|hit|"
    r"close\s+(?:this\s+)?(?:popup|dialog|modal|window)|"
    r"open\s+(?:the\s+)?(?:second|first|third|\d+(?:st|nd|rd|th)?)\s+tab|"
    r"scroll\s+until|"
    r"find\s+the\s+\w+\s+button|"
    r"reply\s+to\s+this|"
    r"read\s+this\s+error|"
    r"what\s+application\s+is\s+open|"
    r"blue\s+button|download\s+button|login\s+button|"
    r"checkbox|dropdown|menu\s+item"
    r")\b",
    re.I,
)


def is_visual_command(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Pure desktop fast commands are not visual
    if re.match(
        r"^(?:open|launch|close|focus|volume|mute|unmute|copy|paste|undo)\b",
        t,
        re.I,
    ) and not re.search(r"\b(button|tab|popup|dialog|checkbox|on\s+screen)\b", t, re.I):
        return False
    return bool(_VISUAL_HINT.search(t))


def plan_from_text(text: str) -> ScreenPlan:
    t = (text or "").strip()
    low = t.lower()

    # What application is open?
    if re.search(r"\bwhat\s+application\s+is\s+open\b|\bwhat(?:'s| is)\s+(?:this\s+)?(?:app|window)\b", low):
        return ScreenPlan(action="describe", args={"mode": "app"}, confidence=0.95, say="")

    # Read error
    if re.search(r"\bread\s+(?:this\s+)?(?:error|message|text)\b", low):
        return ScreenPlan(action="read", args={"focus": "error"}, confidence=0.9, needs_vlm=True)

    # Close popup
    if re.search(r"\bclose\s+(?:this\s+)?(?:popup|dialog|modal)\b", low):
        return ScreenPlan(
            action="click",
            args={"query": "close", "role_hint": "button"},
            confidence=0.88,
        )

    # Open Nth tab
    m = re.search(
        r"\b(?:open|switch\s+to|go\s+to)\s+(?:the\s+)?"
        r"(first|second|third|1st|2nd|3rd|last)\s+tab\b",
        low,
    )
    if m:
        return ScreenPlan(
            action="open_tab",
            args={"ordinal": m.group(1)},
            confidence=0.9,
        )

    # Scroll until find X
    m = re.search(r"\bscroll\s+until\s+(?:you\s+)?(?:find|see)\s+(.+)$", low)
    if m:
        return ScreenPlan(
            action="scroll",
            args={"until": m.group(1).strip(), "direction": "down", "max_steps": 8},
            confidence=0.85,
        )

    # Reply to this message
    if re.search(r"\breply\s+to\s+(?:this|the)\s+message\b", low):
        return ScreenPlan(
            action="click",
            args={"query": "reply", "role_hint": "button"},
            confidence=0.8,
            needs_vlm=True,
        )

    # Find the download button
    m = re.search(r"\bfind\s+(?:the\s+)?(.+?)\s+button\b", low)
    if m:
        return ScreenPlan(
            action="click",
            args={"query": m.group(1).strip() + " button", "role_hint": "button"},
            confidence=0.88,
        )

    # Click / press target
    m = re.search(
        r"\b(?:click|press|tap|hit)\s+(?:on\s+)?(?:the\s+)?(.+)$",
        low,
    )
    if m:
        target = m.group(1).strip(" .,!?")
        role = ""
        if "tab" in target:
            role = "tab"
        elif "checkbox" in target:
            role = "checkbox"
        elif "menu" in target:
            role = "menuitem"
        elif "button" in target or any(
            k in target for k in ("login", "download", "submit", "ok", "cancel")
        ):
            role = "button"
        return ScreenPlan(
            action="click",
            args={"query": target, "role_hint": role},
            confidence=0.86,
            needs_vlm=("blue" in target or "red" in target or "green" in target),
        )

    return ScreenPlan(action="none", confidence=0.0)
