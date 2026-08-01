"""NEURON Blender Agent — Blender Python API expert (compose-only)."""

from __future__ import annotations

from neuron.blender_agent.bridge import maybe_handle_blender
from neuron.blender_agent.detect import looks_like_blender
from neuron.blender_agent.orchestrator import dispatch, orchestrate
from neuron.blender_agent.runner import find_blender, assets_root
from neuron.blender_agent.types import BlenderCapability


def tool_blender_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(BlenderCapability.STATUS.value, {})
    return ok(r.say, state=r.to_dict(), method="blender_agent")


def tool_blender_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    dry = args.get("dry_run")
    dry_run = bool(dry) if dry is not None else None
    if cap:
        r = dispatch(cap, {k: v for k, v in args.items() if k not in ("capability", "request", "dry_run")}, dry_run=bool(dry) if dry is not None else False)
        return ok(r.say, state=r.to_dict(), method="blender_agent") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed")), dry_run=dry_run)
    return ok(say, state=meta, method="blender_agent") if acted else fail(say, state=meta)


def tool_blender_script(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    src = str(args.get("source") or args.get("code") or "").strip()
    if not src:
        return fail("Need bpy source code.")
    r = dispatch(BlenderCapability.RUN_SCRIPT.value, {"source": src}, dry_run=bool(args.get("dry_run", False)))
    return ok(r.say, state=r.to_dict(), method="blender_agent") if r.ok else fail(r.error or r.say, state=r.to_dict())


__all__ = [
    "maybe_handle_blender",
    "looks_like_blender",
    "orchestrate",
    "dispatch",
    "find_blender",
    "assets_root",
    "BlenderCapability",
    "tool_blender_status",
    "tool_blender_run",
    "tool_blender_script",
]
