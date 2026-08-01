"""Detect OS-shell intents — never steal Category A FastIntent commands."""

from __future__ import annotations

import re
from typing import Any

from neuron.os.types import CapabilityId

# Same spirit as FastIntent Category A — leave these alone
_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|focus\s+\w+|stop|cancel|confirm|yes|"
    r"screenshot|what('?s| is) on (my )?screen)$",
    re.I,
)

_OS_STATUS = re.compile(r"\b(os status|neuron os|system status|desktop os|operating system)\b", re.I)
_LAUNCH = re.compile(r"\b(?:launch|start app|universal launch)\s+(.+)$", re.I)
_WINDOWS = re.compile(
    r"\b(list windows|show windows|window manager|move (this )?window|"
    r"minimize|maximize|focus window|active window)\b",
    re.I,
)
_MONITOR = re.compile(r"\b(system monitor|running (apps|processes)|pc status|resource snapshot)\b", re.I)
_NOTIFY = re.compile(r"\b(notify|notification|alert me|tell me when)\b", re.I)
_AUTOMATION = re.compile(
    r"\b(automation hub|list workflows|run workflow|start recording workflow|"
    r"workflow list)\b",
    re.I,
)
_VOICE = re.compile(r"\b(voice[- ]first|hands[- ]free status|voice status)\b", re.I)
_CONTEXT = re.compile(r"\b(context engine|what('?s| is) (my )?context|session context)\b", re.I)
_PLUGINS = re.compile(r"\b(list plugins|plugin status|installed plugins)\b", re.I)
_LEARNING = re.compile(r"\b(learning status|what have you learned|habit status)\b", re.I)
_MEMORY = re.compile(r"\b(os memory|memory status)\b", re.I)


def looks_like_os_shell(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    if _OS_STATUS.search(t):
        return True
    if any(p.search(t) for p in (
        _LAUNCH, _WINDOWS, _MONITOR, _NOTIFY, _AUTOMATION, _VOICE, _CONTEXT, _PLUGINS, _LEARNING, _MEMORY,
    )):
        return True
    # Explicit OS prefix
    low = t.lower()
    if low.startswith("os ") or low.startswith("neuron os"):
        return True
    return False


def classify_os_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if _OS_STATUS.search(t) or low in ("os", "os status", "neuron os"):
        return {"kind": "status", "capability": "status", "args": {}}

    m = _LAUNCH.search(t)
    if m:
        return {
            "kind": "dispatch",
            "capability": CapabilityId.LAUNCHER.value,
            "args": {"name": m.group(1).strip()},
            "text": t,
        }

    if _WINDOWS.search(t):
        op = "list"
        if "active" in low or "foreground" in low:
            op = "active"
        elif "minimize" in low:
            op = "minimize"
        elif "maximize" in low:
            op = "maximize"
        elif "move" in low:
            op = "move"
        elif "focus" in low:
            op = "focus"
        name = ""
        m2 = re.search(r"\b(?:focus|minimize|maximize)\s+(\w+)", t, re.I)
        if m2:
            name = m2.group(1)
        return {
            "kind": "dispatch",
            "capability": CapabilityId.WINDOW_MANAGER.value,
            "args": {"op": op, "name": name},
            "text": t,
        }

    if _MONITOR.search(t):
        return {"kind": "dispatch", "capability": CapabilityId.SYSTEM_MONITOR.value, "args": {}, "text": t}

    if _NOTIFY.search(t):
        msg = t
        m3 = re.search(r"notify(?:\s+me)?(?:\s+that)?\s+(.+)$", t, re.I)
        if m3:
            msg = m3.group(1)
        return {
            "kind": "dispatch",
            "capability": CapabilityId.NOTIFICATIONS.value,
            "args": {"message": msg},
            "text": t,
        }

    if _AUTOMATION.search(t):
        op = "list"
        if "run workflow" in low:
            op = "run"
        elif "record" in low:
            op = "record"
        return {
            "kind": "dispatch",
            "capability": CapabilityId.AUTOMATION_HUB.value,
            "args": {"op": op},
            "text": t,
        }

    if _VOICE.search(t):
        return {"kind": "dispatch", "capability": CapabilityId.VOICE_FIRST.value, "args": {}, "text": t}

    if _CONTEXT.search(t):
        return {"kind": "dispatch", "capability": CapabilityId.CONTEXT.value, "args": {"text": t}, "text": t}

    if _PLUGINS.search(t):
        return {"kind": "dispatch", "capability": CapabilityId.PLUGINS.value, "args": {}, "text": t}

    if _LEARNING.search(t):
        return {"kind": "dispatch", "capability": CapabilityId.LEARNING.value, "args": {}, "text": t}

    if _MEMORY.search(t):
        return {"kind": "dispatch", "capability": CapabilityId.MEMORY.value, "args": {"op": "prompt"}, "text": t}

    # os <capability> ...
    m4 = re.match(r"^(?:os|neuron os)\s+(\w+)\s*(.*)$", t, re.I)
    if m4:
        word = m4.group(1).lower()
        rest = m4.group(2).strip()
        cmap = {
            "launch": CapabilityId.LAUNCHER.value,
            "launcher": CapabilityId.LAUNCHER.value,
            "windows": CapabilityId.WINDOW_MANAGER.value,
            "window": CapabilityId.WINDOW_MANAGER.value,
            "monitor": CapabilityId.SYSTEM_MONITOR.value,
            "notify": CapabilityId.NOTIFICATIONS.value,
            "automation": CapabilityId.AUTOMATION_HUB.value,
            "voice": CapabilityId.VOICE_FIRST.value,
            "context": CapabilityId.CONTEXT.value,
            "vision": CapabilityId.VISION.value,
            "memory": CapabilityId.MEMORY.value,
            "learning": CapabilityId.LEARNING.value,
            "plugins": CapabilityId.PLUGINS.value,
            "plan": CapabilityId.AI_PLANNING.value,
            "computer": CapabilityId.COMPUTER_USE.value,
            "status": "status",
        }
        cap = cmap.get(word)
        if cap == "status":
            return {"kind": "status", "capability": "status", "args": {}}
        if cap == CapabilityId.LAUNCHER.value:
            return {"kind": "dispatch", "capability": cap, "args": {"name": rest or "Chrome"}, "text": t}
        if cap:
            return {
                "kind": "dispatch",
                "capability": cap,
                "args": {"text": rest or t, "op": "list", "request": rest or t, "query": rest or t},
                "text": rest or t,
            }

    return {"kind": "help", "capability": "", "args": {}, "text": t}
