"""Multi-device orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.multi_device import control, registry, sync as sync_mod, transport
from neuron.multi_device.detect import classify_md_intent
from neuron.multi_device.identity import local_device
from neuron.multi_device.types import DeviceKind, MDCapability, MDResult, SyncChannel


def _resolve_target(target: str) -> str | None:
    t = (target or "").lower().replace(" ", "_")
    if t in ("remote", "remote_pc", "pc"):
        t = DeviceKind.REMOTE_PC.value
    # Prefer selected if kind matches, else first of kind, else by name/id
    sel = registry.selected_device()
    if t in {k.value for k in DeviceKind}:
        if sel.kind == t:
            return sel.id
        for d in registry.list_devices():
            if d.kind == t and d.role != "local":
                return d.id
        for d in registry.list_devices():
            if d.kind == t:
                return d.id
        return None
    d = registry.get_device(target)
    return d.id if d else None


def dispatch(capability: str, args: dict[str, Any] | None = None) -> MDResult:
    args = args or {}
    registry.ensure_local_registered()

    if capability == MDCapability.STATUS.value:
        devices = registry.list_devices()
        local = local_device()
        sel = registry.selected_device()
        kinds = sorted({d.kind for d in devices})
        say = (
            f"Multi-device online. Local={local.name} ({local.kind}); "
            f"fleet={len(devices)}; kinds={', '.join(kinds)}; "
            f"selected={sel.name}."
        )
        return MDResult(
            ok=True,
            say=say,
            capability=capability,
            data={"local": local.to_dict(), "devices": [d.to_dict() for d in devices], "selected": sel.to_dict(), "channels": sync_mod.ALL_CHANNELS},
        )

    if capability == MDCapability.LIST.value:
        devices = registry.list_devices()
        lines = ", ".join(f"{d.name}[{d.kind}]" for d in devices[:12])
        return MDResult(ok=True, say=f"{len(devices)} devices: {lines}.", capability=capability, data={"devices": [d.to_dict() for d in devices]})

    if capability == MDCapability.REGISTER.value or capability == MDCapability.PAIR.value:
        name = str(args.get("name") or "Peer")
        kind = str(args.get("kind") or DeviceKind.REMOTE_PC.value)
        host = str(args.get("host") or "")
        dev = registry.register_device(name, kind=kind, host=host, port=int(args.get("port") or 8765), meta=args.get("meta"))
        return MDResult(ok=True, say=f"Registered {dev.name} as {dev.kind} ({dev.id}).", acted=True, capability=capability, data={"device": dev.to_dict()})

    if capability == MDCapability.REMOVE.value:
        pid = str(args.get("id") or "")
        ok = registry.remove_device(pid)
        return MDResult(ok=ok, say=f"Removed {pid}." if ok else f"Could not remove {pid}.", acted=ok, capability=capability)

    if capability == MDCapability.SELECT.value:
        target = str(args.get("target") or args.get("id") or "")
        did = _resolve_target(target) or target
        d = registry.select_device(did)
        if not d:
            return MDResult(ok=False, error="Device not found", say=f"No device matching {target}.", capability=capability)
        return MDResult(ok=True, say=f"Selected {d.name} ({d.kind}).", acted=True, capability=capability, data={"device": d.to_dict()})

    if capability == MDCapability.SYNC.value:
        channels = args.get("channels") or sync_mod.ALL_CHANNELS
        if isinstance(channels, str):
            channels = [channels]
        channels = [c if c in sync_mod.ALL_CHANNELS else c for c in channels]
        # map aliases
        channels = [SyncChannel.MEMORY.value if c == "memory" else c for c in channels]
        target = args.get("device") or registry.selected_device().id
        dry = bool(args.get("dry_run"))
        r = transport.sync_device(str(target), list(channels), dry_run=dry)
        return MDResult(
            ok=bool(r.get("ok")),
            say=f"Synced {', '.join(channels)} with {target}.",
            acted=True,
            capability=capability,
            data=r,
        )

    if capability == MDCapability.SYNC_ALL.value:
        channels = args.get("channels")
        if isinstance(channels, str):
            channels = [channels]
        r = transport.sync_all(channels, dry_run=bool(args.get("dry_run")))
        return MDResult(
            ok=True,
            say=f"Synced channels {', '.join(r.get('channels') or [])} across fleet.",
            acted=True,
            capability=capability,
            data=r,
        )

    if capability == MDCapability.CONTROL.value:
        target = str(args.get("target") or args.get("device") or "")
        command = str(args.get("command") or "status").strip()
        did = _resolve_target(target) or registry.selected_device().id
        r = control.send_command(did, command, confirmed=bool(args.get("confirmed")), execute_local=bool(args.get("execute_local")))
        if not r.get("ok"):
            return MDResult(ok=False, error=r.get("error") or "control failed", say=r.get("error") or "control failed", capability=capability)
        dev = r.get("device") or {}
        return MDResult(
            ok=True,
            say=f"Sent to {dev.get('name')}: {command!r}.",
            acted=True,
            capability=capability,
            data=r,
        )

    return MDResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False) -> tuple[str, bool, dict]:
    intent = classify_md_intent(text)
    cap = intent.get("capability") or MDCapability.STATUS.value
    args = dict(intent.get("args") or {})
    if confirmed:
        args["confirmed"] = True
    result = dispatch(cap, args)
    meta = {
        "path": "multi_device",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Multi-device failed.", True, meta
