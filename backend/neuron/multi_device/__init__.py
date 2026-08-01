"""NEURON Multi-Device — control + sync across desktop/laptop/remote/VM/cloud (compose-only)."""

from __future__ import annotations

from neuron.multi_device.bridge import maybe_handle_multi_device
from neuron.multi_device.detect import looks_like_multi_device
from neuron.multi_device.orchestrator import dispatch, orchestrate
from neuron.multi_device.types import DeviceKind, MDCapability, SyncChannel


def tool_multi_device_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(MDCapability.STATUS.value, args or {})
    return ok(r.say, state=r.to_dict(), method="multi_device")


def tool_multi_device_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="multi_device") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)))
    return ok(say, state=meta, method="multi_device") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_multi_device",
    "looks_like_multi_device",
    "orchestrate",
    "dispatch",
    "MDCapability",
    "DeviceKind",
    "SyncChannel",
    "tool_multi_device_status",
    "tool_multi_device_run",
]
