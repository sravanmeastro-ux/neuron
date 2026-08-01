"""Detect multi-device intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.multi_device.types import DeviceKind, MDCapability, SyncChannel

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_MD = re.compile(
    r"("
    r"multi[- ]?device|sync (memory|tasks|voice|plugins|projects)|"
    r"register (device|laptop|desktop|vm|cloud|remote)|"
    r"list devices|pair (device|laptop|pc)|"
    r"control (the )?(laptop|desktop|remote|vm|cloud)|"
    r"sync (all )?devices|device fleet|remote pc|"
    r"select device|switch (to )?(laptop|desktop|vm|cloud)"
    r")",
    re.I,
)


def looks_like_multi_device(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("multi device") or low.startswith("multi-device") or low in ("device status", "list devices"):
        return True
    return bool(_MD.search(t))


def classify_md_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if low in ("multi device", "multi-device", "device status", "multi device status"):
        return {"capability": MDCapability.STATUS.value, "args": {}}

    if re.search(r"\blist devices\b", low) or "device fleet" in low:
        return {"capability": MDCapability.LIST.value, "args": {}}

    if re.search(r"\bsync all devices\b", low):
        return {"capability": MDCapability.SYNC_ALL.value, "args": {}}

    m = re.search(r"\bsync (memory|tasks|voice|plugins|projects)\b", low)
    if m:
        return {"capability": MDCapability.SYNC.value, "args": {"channels": [m.group(1)]}}

    if re.search(r"\bsync (all )?devices|synchronize (devices|memory|tasks)\b", low):
        return {"capability": MDCapability.SYNC_ALL.value, "args": {}}

    m = re.search(r"\b(?:register|pair)\s+(?:a\s+)?(laptop|desktop|remote\s*pc|vm|cloud|device)\s*(.*)$", low)
    if m:
        kind = m.group(1).replace(" ", "_")
        if kind == "remote_pc" or "remote" in kind:
            kind = DeviceKind.REMOTE_PC.value
        name = (m.group(2) or "").strip(" .") or kind.replace("_", " ").title()
        if kind == "device":
            kind = DeviceKind.REMOTE_PC.value
        return {"capability": MDCapability.REGISTER.value, "args": {"name": name, "kind": kind}}

    m = re.search(r"\b(?:select|switch to)\s+(laptop|desktop|remote|vm|cloud|device)\b", low)
    if m:
        return {"capability": MDCapability.SELECT.value, "args": {"target": m.group(1)}}

    m = re.search(r"\bcontrol (?:the )?(laptop|desktop|remote(?:\s*pc)?|vm|cloud)\s*[:\-]?\s*(.*)$", low)
    if m:
        return {
            "capability": MDCapability.CONTROL.value,
            "args": {"target": m.group(1).replace(" ", "_"), "command": (m.group(2) or "").strip() or "status"},
        }

    return {"capability": MDCapability.STATUS.value, "args": {}}
