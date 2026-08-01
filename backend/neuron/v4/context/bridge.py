"""Bridges: ContextEngine events, CapabilityRouter parity, Recovery CLARIFY."""

from __future__ import annotations

from typing import Any

from neuron.v4.context.engine import get_conversation_engine
from neuron.v4.context.types import RouteDest, UnderstandingResult


def understand_for_agent(raw: str) -> UnderstandingResult:
    """Shared understanding used by AgentLoop path (and tests)."""
    eng = get_conversation_engine()
    return eng.understand(raw)


def sync_context_engine_command(raw: str) -> None:
    try:
        from neuron.v3.context_engine import get_engine

        get_engine().on_user_command(raw)
    except Exception:
        pass


def on_opavr_verified(
    *,
    action: str,
    args: dict | None,
    ok: bool,
    uncertain: bool = False,
    observation: dict | None = None,
    note: str = "",
) -> None:
    eng = get_conversation_engine()
    if uncertain:
        status = "UNCERTAIN"
    elif ok:
        status = "SUCCESS"
    else:
        status = "FAILURE"
    eng.apply_verified(
        action=action,
        args=args,
        status=status,
        observation=observation,
        summary=note,
    )


def on_ask_user_clarify(
    prompt: str,
    *,
    original_goal: str = "",
    options: list[dict] | None = None,
    source: str = "ask_user",
) -> None:
    from neuron.v4.context import clarify as clarify_mod

    eng = get_conversation_engine()
    eng.set_pending_clarification(
        clarify_mod.set_clarification(
            prompt=prompt,
            original_goal=original_goal,
            options=options,
            source=source,
        )
    )


def on_recovery_decision(decision, *, goal_text: str = "", plan_id: str = "") -> None:
    from neuron.v4.recover.types import RecoveryKind

    if decision is None:
        return
    kind = getattr(decision, "kind", None)
    if kind is RecoveryKind.CLARIFY or str(getattr(kind, "value", kind)) == "CLARIFY":
        get_conversation_engine().on_recovery_clarify(
            decision, goal_text=goal_text, plan_id=plan_id
        )


def routing_parity_check(
    raw: str,
    *,
    understanding: UnderstandingResult | None = None,
) -> dict[str, Any]:
    """
    Compare contextual rewrite semantics for FAST_PATH vs hierarchical Goal text.
    Returns mismatch info; increments engine.stats['routing_mismatches'] on conflict.
    """
    eng = get_conversation_engine()
    u = understanding or eng.understand(raw)
    rewritten = (u.rewritten_command or "").strip().lower()
    goal_text = ""
    try:
        pg = eng.to_plan_goal(u)
        goal_text = (pg.normalized or pg.text or "").strip().lower()
    except Exception:
        goal_text = rewritten

    # Fast path expected command = rewritten (same context semantics)
    fast = rewritten
    hier = goal_text or rewritten
    mismatch = 0
    # Normalize trivial whitespace / filler differences
    if _norm(fast) != _norm(hier):
        # Allow hierarchical to be a compound expansion of fast
        if _norm(fast) not in _norm(hier) and _norm(hier) not in _norm(fast):
            mismatch = 1
            eng.stats["routing_mismatches"] += 1

    return {
        "raw": raw,
        "fast_path": fast,
        "hierarchical": hier,
        "route": u.route.value,
        "mismatch": mismatch,
        "continuity": u.continuity.value,
    }


def _norm(s: str) -> str:
    import re

    return re.sub(r"\s+", " ", (s or "").strip().lower())


def cancel_for_stop() -> None:
    get_conversation_engine().cancel_transient()
    try:
        from neuron.v3.context_engine import get_engine

        # Do not wipe entire ContextEngine session on stop — only unsafe pendings in V4
        _ = get_engine
    except Exception:
        pass


__all__ = [
    "understand_for_agent",
    "sync_context_engine_command",
    "on_opavr_verified",
    "on_ask_user_clarify",
    "on_recovery_decision",
    "routing_parity_check",
    "cancel_for_stop",
    "RouteDest",
]
