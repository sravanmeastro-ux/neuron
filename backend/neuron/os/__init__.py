"""NEURON OS — operating-system layer with central orchestration."""

from __future__ import annotations

from neuron.os.bridge import maybe_handle_os
from neuron.os.detect import looks_like_os_shell
from neuron.os import facade
from neuron.os.kernel import boot, dispatch, status as kernel_status
from neuron.os.orchestrator import orchestrate, route_capability
from neuron.os.types import CapabilityId


def tool_os_status(args: dict | None = None):
    from neuron.windows.result import ok
    st = facade.status()
    return ok(
        f"NEURON OS: {len(st.get('capabilities') or [])} capabilities, session {st.get('session_id')}",
        state=st,
        method="neuron_os",
    )


def tool_os_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("query") or args.get("text") or "").strip()
    cap = str(args.get("capability") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    if cap:
        r = route_capability(cap, **{k: v for k, v in args.items() if k not in ("capability", "confirmed", "request")})
        if r.ok:
            return ok(r.say or "ok", state=r.to_dict(), method="neuron_os")
        return fail(r.error or r.say or "failed", state=r.to_dict(), method="neuron_os")
    if not text:
        return fail("Need request text or capability id.")
    say, acted, meta = orchestrate(text, confirmed=confirmed)
    return ok(say, state=meta, method="neuron_os") if acted else fail(say, state=meta, method="neuron_os")


__all__ = [
    "maybe_handle_os",
    "looks_like_os_shell",
    "orchestrate",
    "route_capability",
    "boot",
    "dispatch",
    "kernel_status",
    "facade",
    "CapabilityId",
    "tool_os_status",
    "tool_os_run",
]
