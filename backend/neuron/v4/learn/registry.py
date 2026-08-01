"""ProcedureRegistry — durable store + CapabilityCatalog sync.

Reuses `neuron.learning.procedures` JSON store for persistence.
Does not create a second memory system.
Learned procedures never bypass AgentLoop — run via run_procedure / expand.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from neuron.v4.learn.learner import get_procedure_learner, reset_procedure_learner
from neuron.v4.learn.types import (
    ProcedureDefinition,
    ProcedureParameter,
    ProcedureSource,
    ProcedureStep,
)

log = logging.getLogger("neuron.v4.learn")

STORE = Path(__file__).resolve().parents[3] / "learned_v4_procedures.json"

_REGISTRY: "ProcedureRegistry | None" = None


def _distinctive_phrases(proc: ProcedureDefinition) -> list[str]:
    """Phrases safe for legacy procedures.match (won't steal atomic tools)."""
    out: list[str] = []
    candidates = list(proc.aliases) + [
        proc.name.replace("_", " "),
        f"{proc.name.replace('_', ' ')} workflow",
        f"run {proc.procedure_id.replace('.', ' ')}",
    ]
    for phrase in candidates:
        p = re.sub(r"\s+", " ", (phrase or "").strip().lower())
        if not p:
            continue
        tokens = [t for t in p.split() if len(t) > 2]
        # Require workflow/procedure marker OR ≥3 content tokens
        if "workflow" in p or "procedure" in p or len(tokens) >= 3:
            if p not in out:
                out.append(p)
    return out[:6] or [proc.procedure_id.replace(".", " ").replace("_", " ")]


def _safe_load() -> dict:
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "procedures" in raw:
            return raw
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("[PROCEDURE] corrupt store ignored: %s", exc)
    return {"procedures": [], "schema": 1, "updated": ""}


def _safe_save(data: dict) -> None:
    data = dict(data)
    data["schema"] = 1
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def definition_to_legacy(proc: ProcedureDefinition) -> dict[str, Any]:
    return {
        "id": proc.procedure_id,
        "domain": (proc.procedure_id.split(".", 1)[0] if "." in proc.procedure_id else "learned"),
        "name": proc.name,
        "say": list(proc.aliases) or [proc.name.replace("_", " ")],
        "params": [p.name for p in proc.parameters],
        "steps": [s.to_legacy_step() for s in proc.steps],
        "builtin": proc.source is ProcedureSource.BUILT_IN,
        "source": proc.source.value.lower(),
        "semantic": True,
        "enabled": proc.enabled,
        "version": proc.version,
        "confidence": proc.confidence,
        "intent_family": proc.intent_family,
        "risk_summary": proc.risk_summary,
        "preconditions": list(proc.preconditions),
        "completion_criteria": list(proc.completion_criteria),
        "meta": {
            "v4": True,
            "evidence_count": proc.evidence_count,
            "attempts": proc.attempts,
            "verified_successes": proc.verified_successes,
        },
    }


def legacy_to_definition(raw: dict[str, Any]) -> ProcedureDefinition | None:
    try:
        steps = []
        for s in raw.get("steps") or []:
            steps.append(
                ProcedureStep(
                    capability_id=str(s.get("capability_id") or s.get("action") or ""),
                    tool=str(s.get("action") or ""),
                    arguments=dict(s.get("args") or {}),
                    expected_result=str(s.get("expected_result") or ""),
                )
            )
        src = str(raw.get("source") or "LEARNED").upper()
        try:
            source = ProcedureSource(src)
        except Exception:
            source = ProcedureSource.LEGACY if raw.get("builtin") else ProcedureSource.LEARNED
        params = [
            ProcedureParameter(name=str(n))
            for n in (raw.get("params") or [])
        ]
        return ProcedureDefinition(
            procedure_id=str(raw.get("id") or ""),
            name=str(raw.get("name") or raw.get("id") or ""),
            description=str(raw.get("description") or ""),
            intent_family=str(raw.get("intent_family") or ""),
            parameters=params,
            steps=steps,
            preconditions=list(raw.get("preconditions") or []),
            completion_criteria=list(raw.get("completion_criteria") or []),
            risk_summary=str(raw.get("risk_summary") or "safe"),
            source=source,
            version=int(raw.get("version") or 1),
            aliases=list(raw.get("say") or []),
            enabled=bool(raw.get("enabled", True)),
            confidence=float(raw.get("confidence") or 0.5),
            evidence_count=int((raw.get("meta") or {}).get("evidence_count") or 0),
        )
    except Exception as exc:
        log.warning("[PROCEDURE] skip corrupt record: %s", exc)
        return None


class ProcedureRegistry:
    """In-memory + JSON registry synced to CapabilityCatalog."""

    def __init__(self) -> None:
        self.learner = get_procedure_learner()

    def load(self) -> int:
        data = _safe_load()
        n = 0
        for raw in data.get("procedures") or []:
            proc = legacy_to_definition(raw)
            if not proc or not proc.procedure_id:
                continue
            self.learner.definitions[proc.procedure_id] = proc
            fp = proc.fingerprint()
            self.learner.by_fingerprint[fp] = proc.procedure_id
            self.learner.versions.setdefault(fp, []).append(proc)
            n += 1
        self.sync_catalog()
        return n

    def persist(self, proc: ProcedureDefinition) -> tuple[bool, str]:
        if not proc.enabled and proc.source is ProcedureSource.LEARNED:
            pass
        # Conservative say-phrases only — avoid stealing atomic capabilities
        say = _distinctive_phrases(proc)
        try:
            from neuron.learning.procedures import save_procedure
            ok, msg, _ = save_procedure(
                skill_id=proc.procedure_id if "." in proc.procedure_id else f"learned.{proc.name}",
                steps=[s.to_legacy_step() for s in proc.steps],
                say=say,
                domain=proc.procedure_id.split(".", 1)[0],
                source="v4_learned",
                meta={
                    "version": proc.version,
                    "confidence": proc.confidence,
                    "intent_family": proc.intent_family,
                    "v4": True,
                },
            )
            if not ok:
                return False, msg
        except Exception as exc:
            log.warning("[PROCEDURE] legacy save bridge: %s", exc)

        data = _safe_load()
        procs = [
            p for p in (data.get("procedures") or [])
            if (p.get("id") or "") != proc.procedure_id
        ]
        procs.append(definition_to_legacy(proc))
        data["procedures"] = procs[-80:]
        try:
            _safe_save(data)
        except Exception as exc:
            return False, f"save failed: {exc}"
        self.sync_catalog()
        return True, "saved"

    def accept_and_register(
        self,
        candidate,
        *,
        force: bool = False,
    ) -> tuple[bool, str, ProcedureDefinition | None]:
        ok, reason, proc = self.learner.accept_candidate(candidate, force=force)
        if not ok or not proc:
            return ok, reason, proc
        saved, smsg = self.persist(proc)
        if not saved:
            # Keep in memory anyway for session
            log.warning("[PROCEDURE] persist soft-fail: %s", smsg)
        self.sync_catalog()
        return True, reason, proc

    def sync_catalog(self) -> int:
        """Expose enabled learned procedures as COMPOSITE/PROCEDURE capabilities."""
        try:
            from neuron.v4.capability import get_capability_catalog
            from neuron.v4.capability.types import (
                CapabilityDescriptor,
                CapabilityDomain,
                CapabilityKind,
            )
            cat = get_capability_catalog()
            n = 0
            for proc in self.learner.list_all():
                existing = cat.get(proc.procedure_id)
                if not proc.enabled:
                    if existing:
                        existing.planner_enabled = False
                    continue
                schema = {p.name: p.param_type for p in proc.parameters}
                # Prefer the registered skill id as tool_name (handler → run_procedure).
                # Avoid re-registering the same capability_id with a different tool_name
                # (that would inflate DUPLICATE_CAPABILITY_IMPLEMENTATION_COUNT).
                tool_name = proc.procedure_id
                if existing and existing.tool_name:
                    tool_name = existing.tool_name
                else:
                    try:
                        from neuron.brain import tool_registry as tr
                        tr.ensure_bootstrapped()
                        if tr.is_registered(proc.procedure_id):
                            tool_name = tr.resolve_name(proc.procedure_id) or proc.procedure_id
                        elif tr.is_registered("run_procedure"):
                            tool_name = "run_procedure"
                    except Exception:
                        tool_name = "run_procedure"

                if existing and existing.capability_id == proc.procedure_id:
                    existing.kind = CapabilityKind.COMPOSITE
                    existing.domain = CapabilityDomain.PROCEDURE
                    existing.description = proc.description or existing.description
                    existing.aliases = list(dict.fromkeys(list(existing.aliases) + list(proc.aliases)))[:8]
                    existing.risk_hint = proc.risk_summary or existing.risk_hint
                    existing.input_schema = schema or existing.input_schema
                    existing.verification_kind = "COMPOSITE"
                    existing.preconditions = list(proc.preconditions) or existing.preconditions
                    existing.planner_enabled = True
                    existing.recovery_enabled = True
                    if proc.intent_family and proc.intent_family not in existing.intent_keys:
                        existing.intent_keys.append(proc.intent_family)
                    existing.tags = list(dict.fromkeys(list(existing.tags) + ["learned", "procedure", f"v{proc.version}"]))
                    existing.determinism = "learned"
                    n += 1
                    continue

                desc = CapabilityDescriptor(
                    capability_id=proc.procedure_id,
                    name=proc.name or proc.procedure_id,
                    domain=CapabilityDomain.PROCEDURE,
                    description=proc.description or f"Learned procedure {proc.name}",
                    tool_name=tool_name,
                    aliases=list(proc.aliases)[:8],
                    kind=CapabilityKind.COMPOSITE,
                    risk_hint=proc.risk_summary or "safe",
                    input_schema=schema,
                    verification_kind="COMPOSITE",
                    preconditions=list(proc.preconditions),
                    planner_enabled=True,
                    fast_path_enabled=False,
                    recovery_enabled=True,
                    intent_keys=[proc.intent_family] if proc.intent_family else ["run_procedure"],
                    tags=["learned", "procedure", f"v{proc.version}"],
                    determinism="learned",
                )
                cat.register(desc)
                n += 1
            if n:
                log.info("[PROCEDURE] catalog sync n=%d", n)
            return n
        except Exception as exc:
            log.warning("[PROCEDURE] catalog sync failed: %s", exc)
            return 0

    def list_procedures(self) -> list[ProcedureDefinition]:
        return self.learner.list_all()

    def get(self, procedure_id: str) -> ProcedureDefinition | None:
        return self.learner.get(procedure_id)

    def disable(self, procedure_id: str) -> str:
        if not self.learner.disable(procedure_id):
            return f"No procedure {procedure_id}."
        p = self.learner.get(procedure_id)
        if p:
            self.persist(p)
        self.sync_catalog()
        return f"Disabled {procedure_id}."

    def enable(self, procedure_id: str) -> str:
        if not self.learner.enable(procedure_id):
            return f"No procedure {procedure_id}."
        p = self.learner.get(procedure_id)
        if p:
            self.persist(p)
        self.sync_catalog()
        return f"Enabled {procedure_id}."

    def delete(self, procedure_id: str) -> str:
        if not self.learner.delete(procedure_id):
            return f"No procedure {procedure_id}."
        data = _safe_load()
        data["procedures"] = [
            p for p in (data.get("procedures") or [])
            if (p.get("id") or "") != procedure_id
        ]
        _safe_save(data)
        try:
            from neuron.learning.procedures import delete_procedure
            delete_procedure(procedure_id)
        except Exception:
            pass
        self.sync_catalog()
        return f"Deleted {procedure_id}."

    def inspect(self, procedure_id: str) -> dict[str, Any] | None:
        p = self.learner.get(procedure_id)
        return p.to_dict() if p else None

    def expand(
        self,
        procedure_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.learner.expand_to_plan_steps(procedure_id, params)

    def match(self, text: str) -> ProcedureDefinition | None:
        return self.learner.match(text)


def get_procedure_registry() -> ProcedureRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ProcedureRegistry()
        try:
            _REGISTRY.load()
        except Exception:
            pass
    return _REGISTRY


def reset_procedure_registry(*, clear_store: bool = False) -> ProcedureRegistry:
    global _REGISTRY
    reset_procedure_learner()
    if clear_store and STORE.exists():
        try:
            STORE.unlink()
        except Exception:
            pass
    _REGISTRY = ProcedureRegistry()
    return _REGISTRY


__all__ = [
    "ProcedureRegistry",
    "get_procedure_registry",
    "reset_procedure_registry",
    "definition_to_legacy",
    "legacy_to_definition",
    "STORE",
]
