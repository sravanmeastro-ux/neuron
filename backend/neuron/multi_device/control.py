"""Cross-device control — route commands to remote/VM/cloud peers."""

from __future__ import annotations

import json
import time
from typing import Any

from neuron.multi_device import registry
from neuron.multi_device.identity import inbox_path, local_device


def send_command(
    device_id: str,
    command: str,
    *,
    confirmed: bool = False,
    execute_local: bool = False,
) -> dict[str, Any]:
    """Enqueue a control command for a device. Optionally execute on local device."""
    dev = registry.get_device(device_id) or registry.selected_device()
    if not dev:
        return {"ok": False, "error": "No target device"}
    envelope = {
        "type": "control",
        "from": local_device().id,
        "to": dev.id,
        "command": command,
        "confirmed": confirmed,
        "ts": time.time(),
    }
    path = inbox_path(dev.id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(envelope) + "\n")

    executed = None
    if execute_local and (dev.role == "local" or dev.id == local_device().id):
        try:
            from neuron.brain import agent as brain_agent
            say, acted, meta = brain_agent.run(command, confirmed=confirmed)
            executed = {"say": say, "acted": acted, "path": (meta or {}).get("path")}
        except Exception as exc:
            executed = {"error": str(exc)}

    return {
        "ok": True,
        "device": dev.to_dict(),
        "envelope": envelope,
        "inbox": str(path),
        "executed": executed,
    }


def pending_commands(device_id: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    did = device_id or local_device().id
    path = inbox_path(did)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return [r for r in rows if r.get("type") == "control"]
