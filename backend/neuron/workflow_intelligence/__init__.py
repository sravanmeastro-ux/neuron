"""NEURON Workflow Intelligence — learn reusable workflows from app observation (compose-only)."""

from __future__ import annotations

from neuron.workflow_intelligence.bridge import maybe_handle_workflow_intelligence
from neuron.workflow_intelligence.detect import looks_like_workflow_intelligence
from neuron.workflow_intelligence.orchestrator import dispatch, orchestrate
from neuron.workflow_intelligence.types import WICapability


def tool_workflow_intel_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(WICapability.STATUS.value, args or {})
    return ok(r.say, state=r.to_dict(), method="workflow_intelligence")


def tool_workflow_intel_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="workflow_intelligence") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)), dry_run=bool(args.get("dry_run", False)))
    return ok(say, state=meta, method="workflow_intelligence") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_workflow_intelligence",
    "looks_like_workflow_intelligence",
    "orchestrate",
    "dispatch",
    "WICapability",
    "tool_workflow_intel_status",
    "tool_workflow_intel_run",
]
