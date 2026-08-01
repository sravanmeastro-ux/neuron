"""NEURON Plugin Market — production SDK layer (compose-only over neuron.plugins)."""

from __future__ import annotations

from neuron.plugin_market.api import HOST_API_VERSION, NeuronPluginAPI, api_docs, get_api
from neuron.plugin_market.bridge import maybe_handle_plugin_market
from neuron.plugin_market.detect import looks_like_plugin_market
from neuron.plugin_market.orchestrator import dispatch, orchestrate
from neuron.plugin_market.types import MarketCapability


def tool_plugin_market_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(MarketCapability.STATUS.value, args or {})
    return ok(r.say, state=r.to_dict(), method="plugin_market")


def tool_plugin_market_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request")}
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="plugin_market") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=bool(args.get("confirmed", False)))
    return ok(say, state=meta, method="plugin_market") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_plugin_market",
    "looks_like_plugin_market",
    "orchestrate",
    "dispatch",
    "MarketCapability",
    "NeuronPluginAPI",
    "get_api",
    "api_docs",
    "HOST_API_VERSION",
    "tool_plugin_market_status",
    "tool_plugin_market_run",
]
