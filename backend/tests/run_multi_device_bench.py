"""Benchmarks for Multi-Device."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.multi_device import looks_like_multi_device, orchestrate, dispatch
    from neuron.multi_device.detect import classify_md_intent
    from neuron.multi_device.types import DeviceKind, MDCapability, SyncChannel
    from neuron.multi_device import registry, sync, transport, control
    from neuron.multi_device.bridge import maybe_handle_multi_device
    from neuron.multi_device.identity import sync_snapshot_dir

    assert not looks_like_multi_device("mute")
    assert not looks_like_multi_device("Open Chrome")
    assert looks_like_multi_device("List devices")
    assert looks_like_multi_device("Sync memory")
    assert looks_like_multi_device("Control laptop: status")
    assert looks_like_multi_device("Register cloud worker")
    print("OK detect")

    assert classify_md_intent("Sync memory")["args"]["channels"] == ["memory"]
    assert classify_md_intent("Sync all devices")["capability"] == MDCapability.SYNC_ALL.value
    print("OK classify")

    fleet = registry.seed_demo_fleet()
    kinds = {d.kind for d in fleet}
    for k in (DeviceKind.DESKTOP, DeviceKind.LAPTOP, DeviceKind.REMOTE_PC, DeviceKind.VM, DeviceKind.CLOUD):
        assert k.value in kinds, f"missing kind {k.value} in {kinds}"
    assert len(registry.list_devices()) >= 5
    print(f"OK fleet n={len(registry.list_devices())} kinds={sorted(kinds)}")

    for ch in SyncChannel:
        payload = sync.collect_channel(ch.value)
        assert payload.get("ok")
        print(f"OK collect {ch.value} files={list((payload.get('files') or {}).keys())[:3]}")

    laptop = next(d for d in registry.list_devices() if d.kind == DeviceKind.LAPTOP.value)
    r = transport.sync_device(laptop.id, [SyncChannel.MEMORY.value, SyncChannel.TASKS.value, SyncChannel.VOICE.value, SyncChannel.PLUGINS.value, SyncChannel.PROJECTS.value], dry_run=True)
    assert r.get("ok"), r
    for ch in SyncChannel:
        assert (sync_snapshot_dir(laptop.id) / f"{ch.value}.json").is_file()
    print("OK sync channels -> laptop snapshots")

    allr = transport.sync_all(dry_run=True)
    assert allr.get("ok")
    print(f"OK sync_all devices={len(allr.get('results') or [])}")

    cmd = control.send_command(laptop.id, "ping from hub")
    assert cmd.get("ok") and cmd.get("envelope", {}).get("command")
    pending = control.pending_commands(laptop.id)
    assert pending
    print(f"OK control pending={len(pending)}")

    say, acted, meta = orchestrate("List devices")
    assert acted and meta.get("path") == "multi_device"
    print(f"OK orchestrate say={say[:90]!r}")

    assert maybe_handle_multi_device("mute") is None
    hit = maybe_handle_multi_device("Multi device status")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("multi_device_status")
    assert tool_registry.get("multi_device_run")
    print("OK tools")

    print("PASS multi_device_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
