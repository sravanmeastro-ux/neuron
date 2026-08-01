"""Voice route orchestrator — LEGACY / SHADOW / CANARY / HIERARCHICAL.

Fails closed to LEGACY. Never creates a second AgentLoop.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from neuron.v4.voice import canary, commit, shadow
from neuron.v4.voice.config import (
    hierarchical_voice_enabled,
    voice_config_snapshot,
    voice_routing_mode,
)
from neuron.v4.voice.execute import execute_hierarchical
from neuron.v4.voice.types import (
    RouteDecision,
    RouteKind,
    VoiceRequest,
    VoiceRoutingMode,
)

log = logging.getLogger("neuron.v4.voice")

_last_shadow: dict[str, Any] | None = None
_last_decision: RouteDecision | None = None


def last_shadow_comparison() -> dict[str, Any] | None:
    return _last_shadow


def last_route_decision() -> RouteDecision | None:
    return _last_decision


def decide_route(
    req: VoiceRequest,
    *,
    tools: list[str] | None = None,
    risk: str = "safe",
    intent_family: str = "",
) -> RouteDecision:
    global _last_decision
    mode = voice_routing_mode()
    fam = intent_family or canary.infer_intent_family(req.normalized or req.text)

    if mode is VoiceRoutingMode.LEGACY or not hierarchical_voice_enabled():
        d = RouteDecision(
            route=RouteKind.LEGACY,
            eligible=False,
            reason="legacy mode or master flag off",
            intent_family=fam,
            request_id=req.request_id,
        )
        _last_decision = d
        return d

    if mode is VoiceRoutingMode.SHADOW:
        d = RouteDecision(
            route=RouteKind.HIERARCHICAL_SHADOW,
            eligible=True,
            reason="shadow: plan-only, legacy executes",
            intent_family=fam,
            request_id=req.request_id,
        )
        _last_decision = d
        return d

    eligible, reason = canary.canary_eligible(
        text=req.normalized or req.text,
        intent_family=fam,
        tools=tools,
        risk=risk,
        stt_confidence=req.stt_confidence,
        include_learned_procedures=False,
    )

    if mode is VoiceRoutingMode.CANARY:
        if eligible:
            d = RouteDecision(
                route=RouteKind.HIERARCHICAL_CANARY,
                eligible=True,
                reason=reason,
                intent_family=fam,
                capability_ids=list(tools or [])[:8],
                risk=risk,
                request_id=req.request_id,
            )
        else:
            d = RouteDecision(
                route=RouteKind.LEGACY,
                eligible=False,
                reason=reason,
                intent_family=fam,
                request_id=req.request_id,
            )
        _last_decision = d
        return d

    # HIERARCHICAL mode — still apply deny for unsafe
    if not eligible and "deny:" in reason:
        d = RouteDecision(
            route=RouteKind.LEGACY,
            eligible=False,
            reason=f"hierarchical deny → legacy: {reason}",
            intent_family=fam,
            request_id=req.request_id,
        )
        _last_decision = d
        return d

    d = RouteDecision(
        route=RouteKind.HIERARCHICAL,
        eligible=True,
        reason=reason if eligible else "hierarchical primary",
        intent_family=fam,
        capability_ids=list(tools or [])[:8],
        risk=risk,
        request_id=req.request_id,
    )
    _last_decision = d
    return d


def maybe_handle_voice(
    raw: str,
    *,
    normalized: str = "",
    loop: Any,
    intent: Any = None,
    v4u: Any = None,
    confirmed: bool = False,
    stt_confidence: float | None = None,
) -> tuple[str | None, bool, dict] | None:
    """
    Entry from agent.run.

    Returns:
      None — fall through to legacy CapabilityRouter / LLM paths
      (say, acted, meta) — hierarchical handled (or shadow recorded + fallthrough via None)

    SHADOW always returns None after recording comparison (legacy must execute).
    """
    global _last_shadow

    text = (normalized or raw or "").strip()
    if not text:
        return None

    fam = ""
    if v4u is not None and getattr(v4u, "goal", None) is not None:
        try:
            fam = str(v4u.goal.intent_family.value)
        except Exception:
            fam = str(getattr(v4u.goal, "intent_family", "") or "")
    act = str(getattr(intent, "action", "") or "") if intent else ""
    fam = canary.infer_intent_family(text, v4_family=fam, intent_action=act)

    req = VoiceRequest(
        text=raw or text,
        normalized=text,
        stt_confidence=stt_confidence,
        intent_family=fam,
    )

    decision = decide_route(req, intent_family=fam)
    log.info(
        "[VOICE] request_id=%s mode_route=%s eligible=%s reason=%s",
        req.request_id,
        decision.route.value,
        decision.eligible,
        decision.reason,
    )

    if decision.route is RouteKind.LEGACY:
        return None

    if decision.route is RouteKind.HIERARCHICAL_SHADOW:
        cmp = shadow.compare_shadow(req, intent=intent)
        _last_shadow = cmp.to_dict()
        # CRITICAL: do not execute hierarchical; legacy continues
        return None

    # CANARY or HIERARCHICAL execute
    say, acted, meta = execute_hierarchical(
        req,
        loop=loop,
        decision=decision,
        confirmed=confirmed,
        normalized=text,
    )
    if say is None and not acted and meta.get("fallback_allowed"):
        # Before commit — fall through to legacy once
        commit.clear_route(req.request_id)
        meta["path"] = "fallback_legacy"
        log.info("[VOICE] fallback to legacy before commit: %s", meta.get("reason"))
        return None

    meta["voice_config"] = voice_config_snapshot()
    commit.clear_route(req.request_id)
    return say, acted, meta


__all__ = [
    "decide_route",
    "maybe_handle_voice",
    "last_shadow_comparison",
    "last_route_decision",
]
