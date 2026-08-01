"""Follow-up / new-goal / ellipsis continuity detection."""

from __future__ import annotations

import re

from neuron.v4.context.types import (
    ContinuityKind,
    ConversationState,
    GoalCandidate,
    IntentFamily,
    ParsedUtterance,
)


_FOLLOW_HINTS = re.compile(
    r"^(?:go\s+to|search|play|make\s+it|fullscreen|the\s+(?:first|second|third|last|next)|"
    r"this\s+one|that\s+one|it\b|them\b|other\s+monitor|actually\b)",
    re.I,
)

_NEW_APP = re.compile(
    r"^(?:open|start|launch|close)\s+(?!youtube\b)",
    re.I,
)


def detect_continuity(
    parsed: ParsedUtterance,
    goal: GoalCandidate,
    state: ConversationState,
    *,
    has_pending_clarify: bool = False,
    has_pending_confirm: bool = False,
) -> ContinuityKind:
    text = (parsed.canonical or "").strip()
    if not text:
        return ContinuityKind.NEW_GOAL

    if has_pending_clarify:
        # Short answers / ordinals / "chrome one" while clarify pending
        if len(text.split()) <= 6 or goal.intent_family in (
            IntentFamily.SELECT,
            IntentFamily.CONFIRMATION,
            IntentFamily.CANCEL,
        ):
            return ContinuityKind.CLARIFICATION_ANSWER

    if has_pending_confirm:
        if re.match(r"^(?:yes|yeah|yep|confirm|proceed|ok|okay)\b", text, re.I):
            return ContinuityKind.CONFIRMATION_ANSWER
        if re.match(r"^(?:no|cancel|never\s+mind|abort)\b", text, re.I):
            return ContinuityKind.CANCEL
        # Unrelated command while confirm pending — new goal (does not authorize)
        return ContinuityKind.NEW_GOAL

    if goal.intent_family is IntentFamily.STOP or re.match(
        r"^(?:neuron\s+)?(?:stop|cancel)\b", text, re.I
    ):
        return ContinuityKind.CANCEL

    if parsed.correction_final:
        return ContinuityKind.CORRECTION

    task = state.task
    if not task.is_fresh() or not (task.active_application or task.goal_text):
        return ContinuityKind.NEW_GOAL

    # Explicit new app open while task active may still be new goal
    if _NEW_APP.match(text) and goal.intent_family is IntentFamily.OPEN:
        name = str(goal.args.get("name") or "").lower()
        cur = (task.active_application or "").lower()
        if name and cur and name not in cur and cur not in name:
            # Different app — new goal unless ellipsis move pattern
            if not re.search(r"\bto\s+monitor\b", text, re.I):
                return ContinuityKind.NEW_GOAL

    # Ellipsis: bare "Unreal Engine tutorials" after search
    if (
        goal.intent_family is IntentFamily.UNKNOWN
        and task.last_query
        and re.search(r"tutorial|video|song|file", text, re.I)
    ):
        return ContinuityKind.ELLIPSIS

    # "Spotify to monitor 1" after move Chrome
    if (
        goal.intent_family is IntentFamily.UNKNOWN
        and re.search(r"\bto\s+monitor\b", text, re.I)
        and task.verified_facts.get("last_move_monitor") is not None
    ):
        return ContinuityKind.ELLIPSIS

    if _FOLLOW_HINTS.match(text) or goal.intent_family in (
        IntentFamily.NAVIGATE,
        IntentFamily.SEARCH,
        IntentFamily.PLAY,
        IntentFamily.FULLSCREEN,
        IntentFamily.SELECT,
        IntentFamily.FOLLOW_UP,
    ):
        return ContinuityKind.FOLLOW_UP

    if goal.intent_family is IntentFamily.MOVE and task.active_application:
        return ContinuityKind.FOLLOW_UP

    return ContinuityKind.NEW_GOAL


def apply_ellipsis(parsed: ParsedUtterance, state: ConversationState) -> str:
    """Expand ellipsis utterances using task context."""
    text = (parsed.canonical or "").strip()
    task = state.task
    if re.search(r"\bto\s+monitor\b", text, re.I) and not re.match(
        r"^(?:move|put|send)\b", text, re.I
    ):
        return f"move {text}"
    if task.last_query and not re.match(r"^(?:search|find|play|open)\b", text, re.I):
        if re.search(r"tutorial|video", text, re.I):
            return f"search {text}"
    return text


__all__ = ["detect_continuity", "apply_ellipsis"]
