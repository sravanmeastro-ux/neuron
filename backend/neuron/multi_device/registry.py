"""Device registry — desktop, laptop, remote PC, VM, cloud."""

from __future__ import annotations

import json
import time
from typing import Any

from neuron.multi_device.identity import devices_path, local_device, node_dir
from neuron.multi_device.types import Device, DeviceKind

_SELECTED: str | None = None


def _load_raw() -> dict[str, Any]:
    path = devices_path()
    if not path.is_file():
        return {"devices": [], "selected": None, "updated": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"devices": [], "selected": None, "updated": 0}


def _save_raw(data: dict[str, Any]) -> None:
    data["updated"] = time.time()
    devices_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_local_registered() -> Device:
    local = local_device()
    data = _load_raw()
    devices = [Device.from_dict(d) for d in (data.get("devices") or [])]
    if not any(d.id == local.id for d in devices):
        devices.append(local)
        data["devices"] = [d.to_dict() for d in devices]
        if not data.get("selected"):
            data["selected"] = local.id
        _save_raw(data)
    node_dir(local.id)
    return local


def list_devices() -> list[Device]:
    ensure_local_registered()
    data = _load_raw()
    return [Device.from_dict(d) for d in (data.get("devices") or [])]


def get_device(device_id: str) -> Device | None:
    for d in list_devices():
        if d.id == device_id or d.name.lower() == (device_id or "").lower():
            return d
    return None


def register_device(
    name: str,
    *,
    kind: str = DeviceKind.REMOTE_PC.value,
    host: str = "",
    port: int = 8765,
    device_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Device:
    ensure_local_registered()
    kind_n = (kind or DeviceKind.REMOTE_PC.value).lower().replace(" ", "_")
    if kind_n in ("remote", "pc", "remote-pc"):
        kind_n = DeviceKind.REMOTE_PC.value
    if kind_n not in {k.value for k in DeviceKind}:
        kind_n = DeviceKind.REMOTE_PC.value
    import re
    import uuid
    did = device_id or (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] + "-" + uuid.uuid4().hex[:6])
    existing = get_device(did) or get_device(name)
    if existing:
        existing.name = name or existing.name
        existing.kind = kind_n
        existing.host = host or existing.host
        existing.port = port
        existing.online = True
        existing.last_seen = time.time()
        if meta:
            existing.meta.update(meta)
        _upsert(existing)
        return existing
    dev = Device(
        id=did,
        name=name or did,
        kind=kind_n,
        host=host or "127.0.0.1",
        port=port,
        online=True,
        role="peer",
        last_seen=time.time(),
        meta=dict(meta or {}),
    )
    _upsert(dev)
    node_dir(dev.id)
    return dev


def _upsert(dev: Device) -> None:
    data = _load_raw()
    rows = [Device.from_dict(d) for d in (data.get("devices") or [])]
    rows = [d for d in rows if d.id != dev.id]
    rows.append(dev)
    data["devices"] = [d.to_dict() for d in rows]
    _save_raw(data)


def remove_device(device_id: str) -> bool:
    local = local_device()
    if device_id == local.id:
        return False
    data = _load_raw()
    before = len(data.get("devices") or [])
    data["devices"] = [d for d in (data.get("devices") or []) if str(d.get("id")) != device_id]
    if data.get("selected") == device_id:
        data["selected"] = local.id
    _save_raw(data)
    return len(data["devices"]) < before


def select_device(device_id: str) -> Device | None:
    global _SELECTED
    d = get_device(device_id)
    if not d:
        return None
    _SELECTED = d.id
    data = _load_raw()
    data["selected"] = d.id
    _save_raw(data)
    return d


def selected_device() -> Device:
    ensure_local_registered()
    data = _load_raw()
    sid = data.get("selected") or _SELECTED
    if sid:
        d = get_device(str(sid))
        if d:
            return d
    return local_device()


def seed_demo_fleet() -> list[Device]:
    """Register representative device kinds for demos/benches."""
    ensure_local_registered()
    local = local_device()
    specs = [
        ("Work Desktop", DeviceKind.DESKTOP.value, "10.0.0.10"),
        ("Work Laptop", DeviceKind.LAPTOP.value, "10.0.0.12"),
        ("Remote Studio PC", DeviceKind.REMOTE_PC.value, "10.0.0.40"),
        ("Dev VM", DeviceKind.VM.value, "192.168.56.10"),
        ("Cloud Worker", DeviceKind.CLOUD.value, "cloud.neuron.local"),
    ]
    # Skip adding a peer with the same kind as local if local already covers it — still add all kinds for demos
    out = [local]
    existing_kinds = {local.kind}
    for name, kind, host in specs:
        # Always register each kind at least once (reuse if already present)
        found = next((d for d in list_devices() if d.kind == kind and d.role != "local"), None)
        if found:
            out.append(found)
            existing_kinds.add(kind)
            continue
        if kind == local.kind and local.role == "local":
            # Local already represents this kind; still add a named peer for fleet demos when useful
            pass
        out.append(register_device(name, kind=kind, host=host, meta={"transport": "file"}))
        existing_kinds.add(kind)
    return list_devices()
