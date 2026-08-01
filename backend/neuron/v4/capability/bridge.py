"""Bridges: CapabilityRouter shared IDs, recovery alternates, metrics."""

from __future__ import annotations

from typing import Any

from neuron.v4.capability.catalog import get_capability_catalog, reset_capability_catalog
from neuron.v4.capability.resolve import resolve_intent


def router_capability_to_canonical(router_id: str) -> str | None:
    cat = get_capability_catalog()
    cap = cat.get(router_id)
    if cap:
        return cap.tool_name
    return cat.canonical_tool(router_id)


def shared_semantic_tool(name: str) -> str | None:
    """Map any router/legacy/skill name to one canonical ToolRegistry tool."""
    return get_capability_catalog().canonical_tool(name)


def suggest_recovery_alternates(
    intent: str,
    args: dict[str, Any] | None = None,
    *,
    tried: set[str] | None = None,
    allow_coords: bool = False,
) -> list[tuple[str, dict[str, Any]]]:
    """RecoveryEngine alternate selection via CapabilityCatalog."""
    cat = get_capability_catalog()
    out: list[tuple[str, dict[str, Any]]] = []
    for cap in cat.find_alternates(intent, tried=tried):
        res = resolve_intent(
            intent,
            args,
            preferred=[cap.capability_id],
            allow_coords=allow_coords,
            tried=tried,
        )
        if res.ok and res.tool:
            try:
                from neuron.safety.levels import BLOCKED
                from neuron.safety.policy import classify
                if classify(res.tool, res.args).tier == BLOCKED:
                    continue
            except Exception:
                pass
            out.append((res.tool, dict(res.args)))
    return out


def coverage_report() -> dict[str, Any]:
    return get_capability_catalog().coverage_report()


__all__ = [
    "router_capability_to_canonical",
    "shared_semantic_tool",
    "suggest_recovery_alternates",
    "coverage_report",
    "get_capability_catalog",
    "reset_capability_catalog",
]
