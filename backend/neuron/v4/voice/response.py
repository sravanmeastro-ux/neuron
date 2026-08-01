"""Typed task outcomes → user/TTS language. LLM cannot invent success."""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.voice.types import TaskOutcomeKind, note_unverified_completion

_DONE_RE = re.compile(
    r"(?i)^\s*(done|okay|ok|completed|sure|finished|all set)[.!]?\s*$"
)


def outcome_from_loop(
    *,
    say: str | None,
    acted: bool,
    loop_meta: dict | None,
    goal: Any = None,
    needs_confirm: Any = None,
    path: str = "",
) -> TaskOutcomeKind:
    meta = loop_meta or {}
    if needs_confirm or meta.get("needs_confirm"):
        return TaskOutcomeKind.WAITING_FOR_CONFIRMATION
    if path in ("ask_user",) or meta.get("path") == "ask_user":
        return TaskOutcomeKind.WAITING_FOR_CLARIFICATION
    status = ""
    if goal is not None:
        status = str(getattr(goal, "status", "") or "")
    status = (status or meta.get("goal_status") or meta.get("status") or "").lower()
    if status in ("interrupted", "cancelled", "canceled"):
        return TaskOutcomeKind.CANCELLED
    if status in ("needs_confirm",):
        return TaskOutcomeKind.WAITING_FOR_CONFIRMATION
    # Verification-aware fields from OPAVR
    verify = str(meta.get("verify_status") or meta.get("final_verify") or "").upper()
    if verify == "UNCERTAIN" or meta.get("uncertain"):
        return TaskOutcomeKind.UNCERTAIN
    if verify == "FAILURE" or status in ("failed", "failure", "error"):
        return TaskOutcomeKind.FAILURE
    if verify == "SUCCESS" or status in ("done", "success", "completed", "ok"):
        return TaskOutcomeKind.SUCCESS
    if meta.get("recovered") and acted and not meta.get("errors"):
        # Recovery claimed success — still require verify if present
        if verify and verify != "SUCCESS":
            return TaskOutcomeKind.UNCERTAIN if verify == "UNCERTAIN" else TaskOutcomeKind.FAILURE
        if verify == "SUCCESS":
            return TaskOutcomeKind.SUCCESS
    if acted and not meta.get("errors"):
        # Hierarchical path: do not treat bare acted as SUCCESS without verify
        if meta.get("hierarchical_voice") and not verify:
            return TaskOutcomeKind.UNCERTAIN
        if meta.get("path") in ("capability", "recipe", "deterministic", "llm", "opavr", "hierarchical"):
            # Legacy paths may lack verify_status — keep prior behavior for non-hierarchical
            if meta.get("hierarchical_voice"):
                return TaskOutcomeKind.UNCERTAIN
            return TaskOutcomeKind.SUCCESS
    if meta.get("errors"):
        return TaskOutcomeKind.FAILURE
    return TaskOutcomeKind.UNCERTAIN if acted else TaskOutcomeKind.FAILURE


def render_response(
    outcome: TaskOutcomeKind,
    *,
    base_say: str | None,
    action_summary: str = "",
    hierarchical: bool = False,
) -> str:
    """Build user-facing text. Hierarchical: never emit unverified 'Done.'"""
    base = (base_say or "").strip()
    if outcome is TaskOutcomeKind.WAITING_FOR_CONFIRMATION:
        return base or "That needs confirmation - say confirm or cancel."
    if outcome is TaskOutcomeKind.WAITING_FOR_CLARIFICATION:
        return base or "Which one did you mean?"
    if outcome is TaskOutcomeKind.CANCELLED:
        return base if base and base != "__STOP_SPEECH__" else "Stopped."
    if outcome is TaskOutcomeKind.REJECTED:
        return base or "Okay, I won't."
    if outcome is TaskOutcomeKind.FAILURE:
        if base and not _DONE_RE.match(base):
            return base
        what = action_summary or "that"
        return f"I couldn't complete {what}."
    if outcome is TaskOutcomeKind.UNCERTAIN:
        if base and not _DONE_RE.match(base):
            if re.search(r"(?i)\b(done|completed|finished|success)\b", base):
                what = action_summary or "that"
                return (
                    f"I tried to {what}, but I couldn't verify that it actually worked."
                )
            return base
        what = action_summary or "that"
        return f"I tried to {what}, but I couldn't verify the result."
    # SUCCESS
    if hierarchical:
        if base and _DONE_RE.match(base):
            return (f"Done - {action_summary}." if action_summary else "Done.")
        return base or (f"Done - {action_summary}." if action_summary else "Done.")
    return base or "Done."


def guard_hierarchical_say(
    say: str | None,
    outcome: TaskOutcomeKind,
    *,
    action_summary: str = "",
) -> str:
    """Ensure hierarchical completion text matches typed outcome."""
    text = render_response(
        outcome,
        base_say=say,
        action_summary=action_summary,
        hierarchical=True,
    )
    # Count only if we still emit unverified success language after guarding
    if outcome is not TaskOutcomeKind.SUCCESS and text and _DONE_RE.match(text.strip()):
        note_unverified_completion()
    return text


__all__ = [
    "outcome_from_loop",
    "render_response",
    "guard_hierarchical_say",
]
