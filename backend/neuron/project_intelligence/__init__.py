"""NEURON Project Intelligence — automatic codebase understanding (compose-only)."""

from __future__ import annotations

from neuron.project_intelligence.bridge import maybe_handle_project_intelligence
from neuron.project_intelligence.detect import looks_like_project_intelligence
from neuron.project_intelligence.orchestrator import dispatch, orchestrate
from neuron.project_intelligence.types import PICapability


def tool_project_intel_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(PICapability.STATUS.value, {"root": (args or {}).get("root")})
    return ok(r.say, state=r.to_dict(), method="project_intelligence")


def tool_project_intel_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    root = args.get("root") or args.get("repo")
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        if root:
            payload["root"] = root
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="project_intelligence") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)), root=root)
    return ok(say, state=meta, method="project_intelligence") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_project_intelligence",
    "looks_like_project_intelligence",
    "orchestrate",
    "dispatch",
    "PICapability",
    "tool_project_intel_status",
    "tool_project_intel_run",
]
