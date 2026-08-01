"""NEURON Self-Healing — detect faults, recover, watchdog (compose-only)."""

from __future__ import annotations

from neuron.self_healing.bridge import maybe_handle_self_healing
from neuron.self_healing.detect import looks_like_self_healing
from neuron.self_healing.orchestrator import dispatch, orchestrate
from neuron.self_healing.types import FaultKind, SHCapability


def tool_self_heal_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(SHCapability.STATUS.value, args or {})
    return ok(r.say, state=r.to_dict(), method="self_healing")


def tool_self_heal_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="self_healing") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)))
    return ok(say, state=meta, method="self_healing") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_self_healing",
    "looks_like_self_healing",
    "orchestrate",
    "dispatch",
    "SHCapability",
    "FaultKind",
    "tool_self_heal_status",
    "tool_self_heal_run",
]
