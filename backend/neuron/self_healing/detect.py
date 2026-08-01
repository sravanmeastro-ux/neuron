"""Detect self-healing intents — never steal Category A or Project Intelligence leak scans."""

from __future__ import annotations

import re
from typing import Any

from neuron.self_healing.types import SHCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_SH = re.compile(
    r"("
    r"self[- ]?heal(?:ing)?|watchdog|system health|health (check|scan)|"
    r"high (cpu|ram|memory)|process (crash|freeze|memory)|"
    r"runtime memory leak|detect (crash|freeze|deadlock)|"
    r"restart failed modules?|auto(?:matic)? recover|"
    r"neuron (crashed|froze|frozen)|deadlock detected|"
    r"start (the )?watchdog|stop (the )?watchdog|enable self[- ]?heal"
    r")",
    re.I,
)


def looks_like_self_healing(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    # Leave static "find memory leaks" to Project Intelligence
    if re.search(r"\bfind memory leaks?\b", low) and "runtime" not in low and "process" not in low:
        return False
    if low.startswith("self heal") or low.startswith("self-heal") or low in ("watchdog status", "system health"):
        return True
    return bool(_SH.search(t))


def classify_sh_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if low in ("self healing", "self-heal status", "watchdog status") or "self heal status" in low:
        return {"capability": SHCapability.STATUS.value, "args": {}}

    if re.search(r"\bstop (the )?watchdog\b", low):
        return {"capability": SHCapability.WATCHDOG_STOP.value, "args": {}}

    if re.search(r"\b(start (the )?watchdog|enable self[- ]?heal|watchdog service)\b", low):
        return {"capability": SHCapability.WATCHDOG_START.value, "args": {"auto_recover": True}}

    if re.search(r"\brestart failed modules?\b", low):
        return {"capability": SHCapability.RESTART_MODULE.value, "args": {"all_failed": True}}

    if re.search(r"\brestart (module|the module)\b", low):
        m = re.search(r"restart (?:module|the module)\s+([\w.\-]+)", low)
        return {"capability": SHCapability.RESTART_MODULE.value, "args": {"name": m.group(1) if m else ""}}

    if re.search(r"\b(auto(?:matic)? recover|recover (now|system|from)|heal (now|system))\b", low):
        return {"capability": SHCapability.RECOVER.value, "args": {"auto": True}}

    if re.search(r"\b(system health|health (check|scan)|scan (for )?(faults|issues)|detect (crash|freeze|deadlock|high))\b", low):
        return {"capability": SHCapability.SCAN.value, "args": {}}

    if re.search(r"\b(high (cpu|ram|memory)|runtime memory leak|process (crash|freeze)|deadlock)\b", low):
        return {"capability": SHCapability.SCAN.value, "args": {"recover": True}}

    return {"capability": SHCapability.HEALTH.value, "args": {}}
