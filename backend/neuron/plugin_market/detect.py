"""Detect Plugin Market intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.plugin_market.types import MarketCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_PM = re.compile(
    r"("
    r"plugin (market|sdk|installer|updater)|install plugin|uninstall plugin|"
    r"update plugins?|hot[- ]?reload plugins?|plugin hot[- ]?reload|"
    r"scaffold (a )?plugin|create plugin|developer sdk|"
    r"plugin permissions|grant plugin|plugin catalog|"
    r"start plugin (hot[- ]?reload|watcher)|stop plugin (hot[- ]?reload|watcher)"
    r")",
    re.I,
)


def looks_like_plugin_market(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("plugin market") or low in ("plugin sdk", "plugins market"):
        return True
    return bool(_PM.search(t))


def classify_market_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if low in ("plugin market", "plugin sdk", "plugin market status"):
        return {"capability": MarketCapability.STATUS.value, "args": {}}

    if re.search(r"\bstop plugin (hot[- ]?reload|watcher)\b", low):
        return {"capability": MarketCapability.WATCH_STOP.value, "args": {}}

    if re.search(r"\b(start plugin (hot[- ]?reload|watcher)|hot[- ]?reload watcher)\b", low):
        return {"capability": MarketCapability.WATCH_START.value, "args": {}}

    if re.search(r"\bhot[- ]?reload plugins?\b", low):
        return {"capability": MarketCapability.HOT_RELOAD.value, "args": {}}

    if re.search(r"\bupdate all plugins\b", low) or low.strip() in ("update plugins", "update plugins."):
        return {"capability": MarketCapability.UPDATE_ALL.value, "args": {}}

    if re.search(r"\bupdate plugin\b", low):
        m = re.search(r"update plugin\s+([\w.\-]+)", low)
        return {"capability": MarketCapability.UPDATE.value, "args": {"id": m.group(1) if m else ""}}

    if re.search(r"\buninstall plugin\b", low):
        m = re.search(r"uninstall plugin\s+([\w.\-]+)", low)
        return {"capability": MarketCapability.UNINSTALL.value, "args": {"id": m.group(1) if m else ""}}

    if re.search(r"\binstall plugin\b", low):
        m = re.search(r"install plugin(?: from)?(?: folder| zip)?[:\s]+(.+)$", low)
        return {"capability": MarketCapability.INSTALL.value, "args": {"source": (m.group(1).strip(" .") if m else "")}}

    if re.search(r"\b(scaffold (a )?plugin|create plugin)\b", low):
        m = re.search(r"(?:scaffold|create)(?: a)? plugin\s+([\w.\-]+)", low)
        return {"capability": MarketCapability.SCAFFOLD.value, "args": {"id": m.group(1) if m else "demo"}}

    if re.search(r"\bplugin catalog\b", low):
        return {"capability": MarketCapability.CATALOG.value, "args": {}}

    if re.search(r"\b(grant plugin|plugin permissions)\b", low):
        m = re.search(r"grant(?: plugin)?\s+([\w.\-]+)\s+(\w+)", low)
        return {
            "capability": MarketCapability.TRUST.value,
            "args": {"id": m.group(1) if m else "", "capability": m.group(2) if m else "filesystem"},
        }

    if re.search(r"\blist plugins\b", low):
        return {"capability": MarketCapability.LIST.value, "args": {}}

    return {"capability": MarketCapability.STATUS.value, "args": {}}
