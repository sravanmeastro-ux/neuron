"""Detect Workflow Intelligence intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.workflow_intelligence.types import WICapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_WI = re.compile(
    r"("
    r"start game development|start coding|prepare for blender|"
    r"workflow intelligence|learn (a )?workflow|learn from observation|"
    r"observe (cursor|github|blender|unreal|vs\s*code|browser)|"
    r"reusable workflow|intelligent workflow|"
    r"start (game )?dev(elopment)?|"
    r"prepare for (coding|unreal|blender)|"
    r"coding workflow|blender workflow|game (dev|development) workflow|"
    r"ensure workflow presets|list (intelligent |learned )?workflows"
    r")",
    re.I,
)


def looks_like_workflow_intelligence(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    # Bare "open chrome" stays FastIntent
    if re.match(r"^open\s+\w+$", low):
        return False
    if low.startswith("workflow intel") or low in ("start coding.", "start coding"):
        return True
    return bool(_WI.search(t))


def classify_wi_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower().rstrip(".!?")

    if "workflow intelligence" in low or low in ("wi status", "workflow intel status"):
        return {"capability": WICapability.STATUS.value, "args": {}}

    if re.search(r"\bensure workflow presets\b", low) or "seed workflows" in low:
        return {"capability": WICapability.ENSURE.value, "args": {}}

    if re.search(r"\blearn (a )?workflow|learn from observation\b", low):
        return {"capability": WICapability.LEARN.value, "args": {}}

    if re.search(r"\blist (intelligent |learned )?workflows\b", low):
        return {"capability": WICapability.LIST.value, "args": {}}

    m = re.search(r"\bobserve\s+(cursor|github|blender|unreal|vs\s*code|vscode|browser)\b", low)
    if m:
        return {"capability": WICapability.OBSERVE.value, "args": {"app": m.group(1).replace("vs code", "vscode")}}

    # Preset runners
    if re.search(r"\bstart game development|start game dev|game development workflow\b", low):
        return {"capability": WICapability.RUN.value, "args": {"preset": "start_game_development"}}
    if re.search(r"\bstart coding|coding workflow|prepare for coding|start development\b", low):
        return {"capability": WICapability.RUN.value, "args": {"preset": "start_coding"}}
    if re.search(r"\bprepare for blender|blender workflow|start blender\b", low):
        return {"capability": WICapability.RUN.value, "args": {"preset": "prepare_for_blender"}}
    if re.search(r"\bprepare for unreal|start unreal workflow\b", low):
        return {"capability": WICapability.RUN.value, "args": {"preset": "start_game_development"}}

    return {"capability": WICapability.SUGGEST.value, "args": {"text": t}}
