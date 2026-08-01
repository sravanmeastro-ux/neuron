"""Routing policy: FAST_PATH vs HIERARCHICAL vs CLARIFY — hierarchical not default yet."""

from __future__ import annotations

from neuron.v4.context.types import (
    ContinuityKind,
    GoalCandidate,
    IntentFamily,
    RouteDest,
    UnderstandingResult,
)


_FAST_FAMILIES = {
    IntentFamily.OPEN,
    IntentFamily.CLOSE,
    IntentFamily.FOCUS,
    IntentFamily.VOLUME,
    IntentFamily.PAUSE,
    IntentFamily.STOP,
    IntentFamily.SCROLL,
}


def decide_route(
    *,
    continuity: ContinuityKind,
    goal: GoalCandidate | None,
    confidence: float,
    needs_clarify: bool = False,
    confirmation_answer: bool = False,
) -> tuple[RouteDest, str]:
    if continuity is ContinuityKind.CANCEL or (
        goal and goal.intent_family is IntentFamily.STOP
    ):
        return RouteDest.STOP, "cancel/stop"

    if confirmation_answer or continuity is ContinuityKind.CONFIRMATION_ANSWER:
        return RouteDest.CONFIRM, "pending confirmation answer"

    if needs_clarify or continuity is ContinuityKind.CLARIFICATION_ANSWER:
        if continuity is ContinuityKind.CLARIFICATION_ANSWER:
            return RouteDest.HIERARCHICAL, "clarification answer resumes plan"
        return RouteDest.CLARIFY, "ambiguous — ask user"

    if goal and goal.args.get("negated"):
        return RouteDest.REJECT, "negated intent — do not act"

    if confidence < 0.45 and goal and goal.intent_family is IntentFamily.UNKNOWN:
        return RouteDest.CLARIFY, "low confidence unknown intent"

    if goal and (goal.multi_step or goal.intent_family is IntentFamily.MULTI_STEP_GOAL):
        return RouteDest.HIERARCHICAL, "compound / multi-step goal"

    if continuity in (
        ContinuityKind.FOLLOW_UP,
        ContinuityKind.ELLIPSIS,
        ContinuityKind.CORRECTION,
    ):
        return RouteDest.HIERARCHICAL, f"contextual {continuity.value.lower()}"

    if goal and goal.intent_family in _FAST_FAMILIES and not goal.multi_step:
        # Simple open/mute etc. — CapabilityRouter fast path
        # Exception: open + monitor constraint → hierarchical-friendly
        if goal.intent_family is IntentFamily.OPEN and goal.args.get("monitor"):
            return RouteDest.HIERARCHICAL, "open with monitor constraint"
        return RouteDest.FAST_PATH, "simple deterministic command"

    if goal and goal.intent_family in (
        IntentFamily.SEARCH,
        IntentFamily.PLAY,
        IntentFamily.NAVIGATE,
        IntentFamily.MOVE,
        IntentFamily.FULLSCREEN,
        IntentFamily.CLICK,
    ):
        # Prefer hierarchical when task continuity likely; still allow fast if isolated
        return RouteDest.HIERARCHICAL, f"{goal.intent_family.value} contextualizable"

    return RouteDest.FAST_PATH, "default fast path (hierarchical not yet default)"


def attach_route(result: UnderstandingResult) -> UnderstandingResult:
    dest, reason = decide_route(
        continuity=result.continuity,
        goal=result.goal,
        confidence=result.confidence,
        needs_clarify=result.route is RouteDest.CLARIFY,
        confirmation_answer=bool(result.confirmation_resolution),
    )
    # Preserve explicit clarify/reject already set
    if result.route in (RouteDest.CLARIFY, RouteDest.REJECT, RouteDest.STOP):
        result.route_reason = result.route_reason or reason
        return result
    if result.clarification_resolution and result.clarification_resolution.get("resolved"):
        result.route = RouteDest.HIERARCHICAL
        result.route_reason = "clarification resolved — resume"
        return result
    result.route = dest
    result.route_reason = reason
    return result


__all__ = ["decide_route", "attach_route"]
