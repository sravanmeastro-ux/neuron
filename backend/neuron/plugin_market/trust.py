"""Trust / permission grants for installed market plugins."""

from __future__ import annotations

import json
import time
from typing import Any

from neuron.plugin_market.paths import trust_path

# Capabilities a plugin may request beyond risk_ceiling
CAPABILITIES = (
    "filesystem",
    "network",
    "shell",
    "ui_automation",
    "clipboard",
    "install_peer",
)


def _load() -> dict[str, Any]:
    path = trust_path()
    if not path.is_file():
        return {"grants": {}, "updated": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"grants": {}, "updated": ""}


def _save(data: dict[str, Any]) -> None:
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    trust_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def grant(plugin_id: str, capability: str) -> dict[str, Any]:
    cap = (capability or "").strip().lower()
    if cap not in CAPABILITIES:
        return {"ok": False, "error": f"Unknown capability (allowed: {', '.join(CAPABILITIES)})"}
    data = _load()
    grants = data.setdefault("grants", {})
    entry = grants.setdefault(plugin_id, {"capabilities": [], "granted_at": ""})
    caps = list(entry.get("capabilities") or [])
    if cap not in caps:
        caps.append(cap)
    entry["capabilities"] = caps
    entry["granted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    grants[plugin_id] = entry
    _save(data)
    return {"ok": True, "plugin": plugin_id, "capabilities": caps}


def revoke(plugin_id: str, capability: str | None = None) -> dict[str, Any]:
    data = _load()
    grants = data.setdefault("grants", {})
    if plugin_id not in grants:
        return {"ok": True, "plugin": plugin_id, "capabilities": []}
    if not capability:
        grants.pop(plugin_id, None)
    else:
        caps = [c for c in (grants[plugin_id].get("capabilities") or []) if c != capability]
        grants[plugin_id]["capabilities"] = caps
    _save(data)
    return {"ok": True, "plugin": plugin_id, "capabilities": (grants.get(plugin_id) or {}).get("capabilities") or []}


def is_granted(plugin_id: str, capability: str) -> bool:
    data = _load()
    entry = (data.get("grants") or {}).get(plugin_id) or {}
    return (capability or "").lower() in (entry.get("capabilities") or [])


def list_grants() -> dict[str, Any]:
    return _load()
