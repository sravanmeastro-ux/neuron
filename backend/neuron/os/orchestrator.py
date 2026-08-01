"""Central orchestration engine — routes OS intents to capabilities."""

from __future__ import annotations

import re
from typing import Any

from neuron.os import kernel
from neuron.os.detect import classify_os_intent, looks_like_os_shell
from neuron.os.types import CapabilityId, OsResult


def orchestrate(
    text: str,
    *,
    confirmed: bool = False,
    loop: Any | None = None,
) -> tuple[str, bool, dict]:
    """
    Central OS orchestration entry.
    Returns (say, acted, meta) for agent bridge.
    """
    kernel.boot()
    intent = classify_os_intent(text)
    cap = intent.get("capability") or ""
    args = dict(intent.get("args") or {})
    args.setdefault("confirmed", confirmed)
    if loop is not None:
        args["loop"] = loop
    if intent.get("text"):
        args.setdefault("text", intent["text"])
        args.setdefault("goal", intent["text"])
        args.setdefault("query", intent["text"])

    # Status / help
    if cap == "status" or intent.get("kind") == "status":
        st = kernel.status()
        caps = ", ".join(st.capabilities)
        say = (
            f"NEURON OS online. Session {st.session_id}. "
            f"{len(st.capabilities)} capabilities: {caps}."
        )
        return say, True, {
            "path": "neuron_os",
            "capability": "status",
            "report": st.to_dict(),
        }

    if not cap:
        return (
            "NEURON OS: say 'os status', 'launch Chrome', 'list windows', "
            "'system monitor', or a multi-step plan.",
            True,
            {"path": "neuron_os", "capability": "help"},
        )

    result: OsResult = kernel.dispatch(cap, args)
    meta = {
        "path": "neuron_os",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
        "report": kernel.status().to_dict(),
    }
    if result.ok:
        return result.say or f"{cap} ok.", True, meta
    return result.error or result.say or f"{cap} failed.", True, meta


def route_capability(capability: str, **kwargs: Any) -> OsResult:
    """Programmatic orchestration API."""
    return kernel.dispatch(capability, kwargs)
