"""Transport + sync orchestration between devices (local-first / peer file bus)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from neuron.multi_device import registry, sync as sync_mod
from neuron.multi_device.identity import inbox_path, local_device
from neuron.multi_device.types import SyncChannel


def push_to_device(device_id: str, channels: list[str] | None = None) -> dict[str, Any]:
    """Collect local channels and write snapshots into the target device node."""
    dev = registry.get_device(device_id)
    if not dev:
        return {"ok": False, "error": f"Unknown device: {device_id}"}
    chans = channels or sync_mod.ALL_CHANNELS
    written = []
    for ch in chans:
        path = sync_mod.write_snapshot(dev.id, ch)
        written.append({"channel": ch, "path": str(path)})
    # Envelope for remote agents
    _enqueue(dev.id, {"type": "sync_push", "from": local_device().id, "channels": chans, "ts": time.time()})
    # Optional HTTP notify if host is not loopback-local file bus only
    notify = _http_notify(dev, {"op": "sync_available", "channels": chans})
    return {"ok": True, "device": dev.to_dict(), "written": written, "notify": notify}


def pull_from_device(device_id: str, channels: list[str] | None = None, *, apply: bool = True, dry_run: bool = False) -> dict[str, Any]:
    """Apply snapshots previously pushed into a device node onto local (or dry-run)."""
    dev = registry.get_device(device_id)
    if not dev:
        return {"ok": False, "error": f"Unknown device: {device_id}"}
    chans = channels or sync_mod.ALL_CHANNELS
    results = []
    for ch in chans:
        snap = sync_mod.read_snapshot(dev.id, ch)
        if not snap:
            # If pulling "from" peer that hasn't pushed, seed from local collect for local→local tests
            if dev.role == "local" or device_id == local_device().id:
                snap = sync_mod.collect_channel(ch)
                sync_mod.write_snapshot(dev.id, ch, snap)
            else:
                results.append({"channel": ch, "ok": False, "error": "no snapshot"})
                continue
        if apply:
            applied = sync_mod.apply_channel(ch, snap, dry_run=dry_run)
            results.append({"channel": ch, "ok": True, "apply": applied})
        else:
            results.append({"channel": ch, "ok": True, "snapshot_meta": snap.get("meta")})
    _enqueue(dev.id, {"type": "sync_pull", "to": local_device().id, "channels": chans, "ts": time.time()})
    ok = all(r.get("ok") for r in results) if results else False
    return {"ok": ok, "device": dev.to_dict(), "results": results}


def sync_device(device_id: str, channels: list[str] | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    """Bidirectional-ish: push local state to device bus, then pull/apply for local mirror."""
    push = push_to_device(device_id, channels)
    # For peer devices, pull applies their snapshots if present; for first sync, push is enough
    pull = pull_from_device(device_id, channels, apply=True, dry_run=dry_run)
    return {"ok": push.get("ok") and pull.get("ok"), "push": push, "pull": pull}


def sync_all(channels: list[str] | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    local = local_device()
    results = []
    for d in registry.list_devices():
        if d.id == local.id:
            # Always refresh local snapshots
            for ch in (channels or sync_mod.ALL_CHANNELS):
                sync_mod.write_snapshot(local.id, ch)
            results.append({"id": d.id, "ok": True, "local_refresh": True})
            continue
        results.append({"id": d.id, **sync_device(d.id, channels, dry_run=dry_run)})
    return {"ok": True, "results": results, "channels": channels or sync_mod.ALL_CHANNELS}


def _enqueue(device_id: str, event: dict[str, Any]) -> None:
    path = inbox_path(device_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def _http_notify(dev, payload: dict[str, Any]) -> dict[str, Any]:
    if not dev.host or dev.host in ("local", "127.0.0.1", "localhost"):
        return {"skipped": True, "reason": "local file bus"}
    if (dev.meta or {}).get("transport") == "file":
        return {"skipped": True, "reason": "file transport"}
    url = f"http://{dev.host}:{dev.port}/neuron/multi_device"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return {"ok": True, "status": getattr(resp, "status", 200)}
    except Exception as exc:
        # Soft-fail — file bus remains source of truth
        return {"ok": False, "error": str(exc), "soft": True}
