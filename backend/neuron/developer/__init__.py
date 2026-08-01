"""NEURON Developer Mode — AI software engineer workflows (compose-only)."""

from __future__ import annotations

from neuron.developer.bridge import maybe_handle_developer
from neuron.developer.detect import looks_like_developer
from neuron.developer.orchestrator import dispatch, orchestrate
from neuron.developer.types import DevCapability


def tool_developer_status(args: dict | None = None):
    from neuron.windows.result import ok
    args = args or {}
    r = dispatch(DevCapability.STATUS.value, {"root": args.get("root")})
    return ok(r.say, state=r.to_dict(), method="developer")


def tool_developer_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    root = args.get("root")
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request", "confirmed")}
        if confirmed and cap in ("build", "test"):
            payload["execute"] = True
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="developer") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=confirmed, root=root)
    return ok(say, state=meta, method="developer") if acted else fail(say, state=meta)


def tool_developer_index(args: dict | None = None):
    from neuron.windows.result import ok
    args = args or {}
    r = dispatch(DevCapability.INDEX.value, {"root": args.get("root")})
    return ok(r.say, state=r.to_dict(), method="developer")


def tool_developer_review(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    r = dispatch(DevCapability.GIT.value, {"op": "review", "root": args.get("root")})
    return ok(r.say, state=r.to_dict(), method="developer") if r.ok else fail(r.error or r.say, state=r.to_dict())


__all__ = [
    "maybe_handle_developer",
    "looks_like_developer",
    "orchestrate",
    "dispatch",
    "DevCapability",
    "tool_developer_status",
    "tool_developer_run",
    "tool_developer_index",
    "tool_developer_review",
]
