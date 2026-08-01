"""NEURON Production Readiness — audit, installer, wizard, diagnostics (compose-only)."""

from __future__ import annotations

from neuron.production.bridge import maybe_handle_production
from neuron.production.detect import looks_like_production
from neuron.production.orchestrator import dispatch, orchestrate
from neuron.production.paths import PRODUCT_NAME, PRODUCT_VERSION
from neuron.production.types import ProdCapability


def tool_production_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(ProdCapability.STATUS.value, args or {})
    return ok(r.say, state=r.to_dict(), method="production")


def tool_production_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="production") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)))
    return ok(say, state=meta, method="production") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_production",
    "looks_like_production",
    "orchestrate",
    "dispatch",
    "ProdCapability",
    "PRODUCT_NAME",
    "PRODUCT_VERSION",
    "tool_production_status",
    "tool_production_run",
]
