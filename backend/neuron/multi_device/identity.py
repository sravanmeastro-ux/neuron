"""Multi-device paths + local identity."""

from __future__ import annotations

import json
import socket
import time
import uuid
from pathlib import Path
from typing import Any

from neuron.multi_device.types import Device, DeviceKind


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    d = backend_root() / "data" / "multi_device"
    d.mkdir(parents=True, exist_ok=True)
    return d


def devices_path() -> Path:
    return data_root() / "devices.json"


def identity_path() -> Path:
    return data_root() / "identity.json"


def node_dir(device_id: str) -> Path:
    d = data_root() / "nodes" / device_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def inbox_path(device_id: str) -> Path:
    return node_dir(device_id) / "inbox.jsonl"


def sync_snapshot_dir(device_id: str) -> Path:
    d = node_dir(device_id) / "sync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def detect_kind() -> str:
    """Best-effort local kind heuristic."""
    try:
        # Laptop-ish if battery present on Windows
        import subprocess
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Battery) -ne $null"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if "True" in (p.stdout or ""):
            return DeviceKind.LAPTOP.value
    except Exception:
        pass
    host = socket.gethostname().lower()
    if any(x in host for x in ("vm", "virtual", "vbox", "qemu", "hyperv")):
        return DeviceKind.VM.value
    return DeviceKind.DESKTOP.value


def load_or_create_identity() -> dict[str, Any]:
    path = identity_path()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    ident = {
        "id": "local-" + uuid.uuid4().hex[:8],
        "name": socket.gethostname() or "NEURON-Local",
        "kind": detect_kind(),
        "host": "127.0.0.1",
        "port": 8765,
        "role": "local",
        "created": time.time(),
    }
    path.write_text(json.dumps(ident, indent=2), encoding="utf-8")
    return ident


def local_device() -> Device:
    ident = load_or_create_identity()
    return Device(
        id=str(ident["id"]),
        name=str(ident.get("name") or "Local"),
        kind=str(ident.get("kind") or DeviceKind.DESKTOP.value),
        host=str(ident.get("host") or "127.0.0.1"),
        port=int(ident.get("port") or 8765),
        online=True,
        role="local",
        last_seen=time.time(),
        meta={"hostname": socket.gethostname()},
    )
