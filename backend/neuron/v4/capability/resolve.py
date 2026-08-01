"""ActionIntent → capability candidates → GroundedAction."""

from __future__ import annotations

import time
from typing import Any

from neuron.v4.capability.catalog import get_capability_catalog
from neuron.v4.capability.types import CapabilityResolution


def _check_preconditions(
    preconditions: list[str],
    args: dict[str, Any],
    *,
    world: Any = None,
    context: Any = None,
) -> tuple[bool, str]:
    for p in preconditions:
        if p == "result_set_or_index":
            if args.get("index") is None and args.get("ordinal") is None and not args.get("result_ref"):
                # Allow if conversation result set exists
                rs = getattr(context, "result_set", None) if context is not None else None
                if context is not None and hasattr(context, "state"):
                    rs = context.state.result_set
                if rs is None or (hasattr(rs, "is_fresh") and not rs.is_fresh()):
                    if args.get("index") is None:
                        return False, "play_result requires result index or fresh result set"
        if p == "target_window_or_app":
            if not (args.get("name") or args.get("app") or args.get("window") or args.get("title")):
                return False, "move/focus requires window or app name"
        if p == "focus_or_target":
            # Soft — allow; recovery/focus handles
            pass
        if p == "browser_or_media_context":
            pass
        if p == "browser_available_or_open":
            pass
    return True, ""


def resolve_intent(
    intent: str,
    args: dict[str, Any] | None = None,
    *,
    world: Any = None,
    context: Any = None,
    preferred: list[str] | None = None,
    allow_coords: bool = False,
    tried: set[str] | None = None,
) -> CapabilityResolution:
    """
    Resolve WHAT (intent) into HOW (registered capability/tool).
    Never invents unregistered tool names.
    """
    t0 = time.perf_counter()
    args = dict(args or {})
    intent = (intent or "").strip().lower()
    catalog = get_capability_catalog()
    tried = set(tried or set())

    # Reject hallucinated explicit tool
    if preferred:
        for p in preferred:
            if p and not catalog.supports(p) and not catalog.get_by_tool(p) and not catalog.canonical_tool(p):
                return CapabilityResolution(
                    ok=False,
                    reason=f"unknown capability {p!r}",
                    unsupported=True,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )

    candidates = []
    if preferred:
        for p in preferred:
            cap = catalog.get(p) or catalog.get_by_tool(p)
            if cap:
                candidates.append(cap)
    for cap in catalog.match_intent(intent):
        if cap.capability_id not in {c.capability_id for c in candidates}:
            candidates.append(cap)

    ranked: list[tuple[int, Any]] = []
    for i, cap in enumerate(candidates):
        if cap.tool_name in tried or cap.capability_id in tried:
            continue
        fail_key = f"{intent}|{cap.tool_name}"
        if catalog.failures.recently_failed(fail_key):
            continue
        ok_pre, pre_reason = _check_preconditions(cap.preconditions, args, world=world, context=context)
        if not ok_pre:
            continue
        # Safety — use module attribute so tests can patch levels.classify
        risk = cap.risk_hint
        try:
            from neuron.safety import levels as safety_levels
            c = safety_levels.classify(cap.tool_name, args)
            risk = c.tier
            if c.tier == safety_levels.BLOCKED:
                continue
        except Exception:
            pass
        # Rank: list order primary, then dotted skill, router shared
        rank = i  # preserve match_intent preference order
        if "." in cap.capability_id:
            rank -= 0
        if cap.fast_path_enabled:
            rank = min(rank, i)
        if intent.startswith("youtube") and cap.capability_id.startswith("youtube."):
            rank -= 50
        if "coords" in (cap.control_methods or []) and not allow_coords:
            rank += 10
        if not allow_coords and cap.tool_name == "click" and args.get("x") is not None:
            rank += 15
        ranked.append((rank, cap, risk))

    if not ranked:
        # Try alternates from recovery catalog path
        alts = catalog.find_alternates(intent, tried=tried)
        for cap in alts:
            ok_pre, _ = _check_preconditions(cap.preconditions, args, world=world, context=context)
            if not ok_pre:
                continue
            try:
                from neuron.safety import levels as safety_levels
                if safety_levels.classify(cap.tool_name, args).tier == safety_levels.BLOCKED:
                    continue
            except Exception:
                pass
            ranked.append((3, cap, cap.risk_hint))

    if not ranked:
        return CapabilityResolution(
            ok=False,
            reason=f"UNSUPPORTED_CAPABILITY for intent={intent}",
            unsupported=True,
            candidates=[c.capability_id for c in candidates][:8],
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    ranked.sort(key=lambda x: (x[0], x[1].capability_id))
    _rank, cap, risk = ranked[0]

    # Validate args
    try:
        from neuron.brain import tool_registry as tr
        ok, err, coerced = tr.validate_args(cap.tool_name, args)
        use_args = coerced if ok else dict(args)
        if not ok and err:
            # Soft: keep args if schema empty
            if cap.input_schema:
                return CapabilityResolution(
                    ok=False,
                    capability=cap,
                    tool=cap.tool_name,
                    reason=f"invalid arguments: {err}",
                    candidates=[c.capability_id for c, _, __ in [(r[1], r[0], r[2]) for r in ranked]][:8]
                    if False else [x[1].capability_id for x in ranked][:8],
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
    except Exception:
        use_args = dict(args)

    needs_confirm = str(risk).lower() in ("confirm", "high")
    return CapabilityResolution(
        ok=True,
        capability=cap,
        tool=cap.tool_name,
        args=use_args,
        reason=f"selected {cap.capability_id}",
        risk=str(risk).lower(),
        verification_kind=cap.verification_kind,
        candidates=[x[1].capability_id for x in ranked][:8],
        needs_confirm=needs_confirm,
        latency_ms=(time.perf_counter() - t0) * 1000,
    )


def resolve_action_intent(action_intent, *, world=None, context=None) -> CapabilityResolution:
    """Accept planner ActionIntent-like object or dict."""
    if action_intent is None:
        return CapabilityResolution(ok=False, reason="empty intent", unsupported=True)
    if isinstance(action_intent, dict):
        intent = str(action_intent.get("intent") or action_intent.get("kind") or "")
        args = dict(action_intent.get("arguments") or action_intent.get("args") or {})
        preferred = action_intent.get("preferred_tools") or action_intent.get("preferred")
    else:
        intent = str(
            getattr(action_intent, "intent", None)
            or getattr(action_intent, "kind", None)
            or getattr(action_intent, "name", None)
            or ""
        )
        args = dict(
            getattr(action_intent, "arguments", None)
            or getattr(action_intent, "args", None)
            or {}
        )
        preferred = getattr(action_intent, "preferred_tools", None)
    return resolve_intent(intent, args, world=world, context=context, preferred=list(preferred or []) or None)


__all__ = ["resolve_intent", "resolve_action_intent"]
