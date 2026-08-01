"""NEURON Unreal Agent — Unreal Engine expert (compose-only)."""

from __future__ import annotations

from neuron.unreal_agent.bridge import maybe_handle_unreal
from neuron.unreal_agent.detect import looks_like_unreal
from neuron.unreal_agent.orchestrator import dispatch, orchestrate
from neuron.unreal_agent.runner import find_engine, find_editor_cmd, find_uproject, assets_root
from neuron.unreal_agent.types import UnrealCapability


def tool_unreal_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(UnrealCapability.STATUS.value, {})
    return ok(r.say, state=r.to_dict(), method="unreal_agent")


def tool_unreal_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    dry = args.get("dry_run")
    confirmed = bool(args.get("confirmed", False))
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request", "dry_run", "confirmed")}
        if confirmed and cap == "packaging":
            payload["execute"] = True
        r = dispatch(cap, payload, dry_run=bool(dry) if dry is not None else False)
        return ok(r.say, state=r.to_dict(), method="unreal_agent") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=confirmed, dry_run=bool(dry) if dry is not None else None)
    return ok(say, state=meta, method="unreal_agent") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_unreal",
    "looks_like_unreal",
    "orchestrate",
    "dispatch",
    "find_engine",
    "find_editor_cmd",
    "find_uproject",
    "assets_root",
    "UnrealCapability",
    "tool_unreal_status",
    "tool_unreal_run",
]
