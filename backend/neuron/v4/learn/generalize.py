"""Generalize verified traces into parameterized ProcedureCandidates."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from neuron.v4.learn.types import (
    ProcedureCandidate,
    ProcedureParameter,
    ProcedureStep,
    TraceStep,
    VerifiedTaskTrace,
)


_QUERY_KEYS = ("query", "text", "q", "search")
_APP_KEYS = ("name", "app", "application")
_MONITOR_KEYS = ("monitor", "monitor_index", "monitor_id")
_ORDINAL_KEYS = ("index", "ordinal", "result_index")


def generalize_traces(traces: list[VerifiedTaskTrace]) -> ProcedureCandidate | None:
    if not traces:
        return None
    # Prefer recovery-successful capability: drop failed-then-recovered tools
    # by keeping last SUCCESS tool per semantic role when recovery_used.
    base = traces[0]
    steps = _normalize_steps(base)
    if len(steps) < 2:
        return None

    # Collect varying values across traces with same tool skeleton
    skeletons = [_skeleton(t) for t in traces]
    if len(set(skeletons)) > 1:
        # Use majority skeleton
        sk = Counter(skeletons).most_common(1)[0][0]
        traces = [t for t in traces if _skeleton(t) == sk]
        if not traces:
            return None
        steps = _normalize_steps(traces[0])

    params: list[ProcedureParameter] = []
    param_names: set[str] = set()

    def _add_param(name: str, ptype: str, required: bool = True) -> None:
        if name in param_names:
            return
        param_names.add(name)
        params.append(ProcedureParameter(name=name, param_type=ptype, required=required))

    # Compare args across traces
    for si, step in enumerate(steps):
        tool = step.tool
        values_by_key: dict[str, list[Any]] = {}
        for tr in traces:
            st = _nth_success_step(tr, si)
            if not st:
                continue
            for k, v in (st.arguments or {}).items():
                values_by_key.setdefault(k, []).append(v)
        for k, vals in values_by_key.items():
            uniq = {str(v).lower() for v in vals if v is not None and str(v) != ""}
            varies = len(uniq) > 1
            # Workflow-facing keys become parameters even when constant (default kept)
            promote_monitor = k in _MONITOR_KEYS
            promote_query = k in _QUERY_KEYS or k == "query"
            promote_ordinal = k in _ORDINAL_KEYS
            if not varies and not (promote_monitor or promote_query or promote_ordinal):
                continue  # true constant (e.g. app=Chrome)
            if promote_query:
                _add_param("query", "string")
                step.param_bindings[k] = "query"
                step.arguments[k] = "{query}"
                if not varies and vals:
                    # keep observed constant as default
                    for p in params:
                        if p.name == "query" and p.default is None:
                            p.default = vals[0]
            elif promote_monitor:
                _add_param("monitor", "monitor")
                step.param_bindings[k] = "monitor"
                step.arguments[k] = "{monitor}"
                if not varies and vals:
                    for p in params:
                        if p.name == "monitor" and p.default is None:
                            p.default = vals[0]
                            p.required = False
            elif k in _APP_KEYS and "open" in (tool or "") and varies:
                _add_param("app", "app", required=False)
                step.param_bindings[k] = "app"
                step.arguments[k] = "{app}"
            elif promote_ordinal:
                _add_param("result_index", "ordinal", required=False)
                step.param_bindings[k] = "result_index"
                step.arguments[k] = "{result_index}"
                if not varies and vals:
                    for p in params:
                        if p.name == "result_index" and p.default is None:
                            p.default = vals[0]
            elif varies:
                pname = re.sub(r"[^a-z0-9_]+", "_", k.lower())[:24] or "value"
                _add_param(pname, "string", required=False)
                step.param_bindings[k] = pname
                step.arguments[k] = "{" + pname + "}"

    # Prefer robust tools when recovery was used: rewrite step tool to final success tool
    for si, step in enumerate(steps):
        for tr in traces:
            st = _nth_success_step(tr, si)
            if st and st.recovery_used and st.tool:
                # Prefer dotted domain skill if present in any success
                if "." in st.tool or st.tool.startswith("youtube") or st.tool.startswith("browser"):
                    step.tool = st.tool
                    step.capability_id = st.capability_id or st.tool

    intent = base.intent_family or "multi_step_workflow"
    name = _name_for(intent, params)
    fp = intent + "|" + "|".join(
        f"{s.tool}:{','.join(sorted(s.param_bindings.values()))}" for s in steps
    )
    conf = min(0.55 + 0.12 * len(traces), 0.92)
    return ProcedureCandidate(
        name=name,
        intent_family=intent,
        parameters=params,
        steps=steps,
        confidence=conf,
        evidence_count=len(traces),
        risk_summary="safe",
        completion_criteria=[s.verification_kind or s.expected_result or "step_ok" for s in steps],
        aliases=_aliases(intent, params),
        fingerprint=fp,
    )


def _normalize_steps(trace: VerifiedTaskTrace) -> list[ProcedureStep]:
    out: list[ProcedureStep] = []
    for st in trace.steps:
        tool = st.tool or st.capability_id
        # Skip raw coord tools
        if tool in ("click", "mouse_click", "drag"):
            continue
        args = {k: v for k, v in (st.arguments or {}).items() if str(k).lower() not in ("x", "y")}
        out.append(
            ProcedureStep(
                capability_id=st.capability_id or tool,
                tool=tool,
                arguments=args,
                expected_result=st.expected_result,
                verification_kind="SUCCESS",
            )
        )
    return out


def _skeleton(trace: VerifiedTaskTrace) -> str:
    return "|".join((s.tool or s.capability_id or "") for s in _normalize_steps(trace))


def _nth_success_step(trace: VerifiedTaskTrace, index: int) -> TraceStep | None:
    norm = _normalize_steps(trace)
    if index >= len(norm):
        return None
    # Map back roughly
    filtered = [s for s in trace.steps if (s.tool or s.capability_id) not in ("click", "mouse_click", "drag")]
    if index < len(filtered):
        return filtered[index]
    return None


def _name_for(intent: str, params: list[ProcedureParameter]) -> str:
    if intent.startswith("youtube"):
        if any(p.name == "query" for p in params):
            return "youtube_search_workflow"
        return "youtube_workflow"
    if "monitor" in intent:
        return "monitor_workflow"
    return intent or "learned_workflow"


def _aliases(intent: str, params: list[ProcedureParameter]) -> list[str]:
    aliases = []
    if intent.startswith("youtube"):
        # Keep phrases distinctive (≥3 content tokens / "workflow") so they
        # do not steal atomic youtube.search via legacy procedures.match.
        aliases.extend([
            "youtube search workflow",
            "do my youtube search workflow",
            "run my youtube search workflow",
        ])
    return aliases


__all__ = ["generalize_traces"]
