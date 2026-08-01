"""User-facing procedure controls (list/inspect/enable/disable/delete/alias)."""

from __future__ import annotations

from typing import Any

from neuron.v4.learn.registry import get_procedure_registry


def list_learned_procedures(limit: int = 20) -> list[dict[str, Any]]:
    reg = get_procedure_registry()
    rows = [p.to_dict() for p in reg.list_procedures()]
    return rows[-limit:]


def inspect_procedure(procedure_id: str) -> dict[str, Any] | None:
    return get_procedure_registry().inspect(procedure_id)


def disable_procedure(procedure_id: str) -> str:
    return get_procedure_registry().disable(procedure_id)


def enable_procedure(procedure_id: str) -> str:
    return get_procedure_registry().enable(procedure_id)


def delete_procedure(procedure_id: str) -> str:
    return get_procedure_registry().delete(procedure_id)


def add_procedure_alias(procedure_id: str, alias: str) -> str:
    reg = get_procedure_registry()
    ok = reg.learner.rename_alias(procedure_id, alias)
    if not ok:
        return f"No procedure {procedure_id}."
    p = reg.get(procedure_id)
    if p:
        reg.persist(p)
        reg.sync_catalog()
    return f"Alias '{alias}' added to {procedure_id}."


def procedures_summary(limit: int = 12) -> str:
    rows = list_learned_procedures(limit=limit)
    if not rows:
        return "No V4 learned procedures yet."
    lines = ["Learned procedures (verified-success only; AgentLoop execution):"]
    for r in rows:
        lines.append(
            f"- {r.get('procedure_id')} v{r.get('version')} "
            f"({'on' if r.get('enabled') else 'off'}) "
            f"conf={r.get('confidence')} evidence={r.get('evidence_count')}"
        )
    return "\n".join(lines)


__all__ = [
    "list_learned_procedures",
    "inspect_procedure",
    "disable_procedure",
    "enable_procedure",
    "delete_procedure",
    "add_procedure_alias",
    "procedures_summary",
]
