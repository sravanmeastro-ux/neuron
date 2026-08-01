"""Clarification + confirmation binding (kept strictly separate)."""

from __future__ import annotations

import re
from typing import Any

from neuron.v4.context.parse import parse_ordinal
from neuron.v4.context.types import ClarificationState, ConfirmationState


def set_clarification(
    *,
    prompt: str,
    original_goal: str = "",
    original_action: str = "",
    options: list[dict[str, Any]] | None = None,
    expected_answer_type: str = "choice",
    source: str = "",
    plan_id: str = "",
    subgoal_id: str = "",
    safety_context: str = "",
) -> ClarificationState:
    return ClarificationState(
        prompt=prompt[:400],
        original_goal=original_goal[:200],
        original_action=original_action[:80],
        options=list(options or []),
        expected_answer_type=expected_answer_type,
        source=source,
        plan_id=plan_id,
        subgoal_id=subgoal_id,
        safety_context=safety_context[:80],
    )


def resolve_clarification(
    text: str,
    pending: ClarificationState | None,
) -> dict[str, Any] | None:
    """
    Resolve a user answer against pending clarification.
    Returns None if not applicable / unresolved.
    """
    if pending is None or not pending.is_active():
        return None
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.match(r"^(?:cancel|never\s+mind|abort|stop)\b", t):
        return {"resolved": False, "cancel": True, "choice": None, "reason": "user_cancel"}
    if re.match(r"^(?:neither|none|no\s+one)\b", t):
        return {"resolved": False, "cancel": False, "choice": None, "reason": "neither"}

    opts = pending.options or []
    # Ordinal
    ord_n = parse_ordinal(t)
    if ord_n is not None and opts:
        idx = ord_n - 1 if ord_n > 0 else len(opts) + ord_n
        if 0 <= idx < len(opts):
            return {
                "resolved": True,
                "cancel": False,
                "choice": opts[idx],
                "index": idx,
                "reason": "ordinal",
            }

    # Label match (chrome one, the right one, …)
    for i, opt in enumerate(opts):
        label = str(opt.get("label") or opt.get("name") or opt.get("app") or "").lower()
        if label and (label in t or t in label):
            return {
                "resolved": True,
                "cancel": False,
                "choice": opt,
                "index": i,
                "reason": "label",
            }
        # "chrome one"
        token = label.split()[0] if label else ""
        if token and re.search(rf"\b{re.escape(token)}\b", t):
            return {
                "resolved": True,
                "cancel": False,
                "choice": opt,
                "index": i,
                "reason": "token",
            }

    if re.search(r"\bright\b", t) and opts:
        return {
            "resolved": True,
            "cancel": False,
            "choice": opts[-1],
            "index": len(opts) - 1,
            "reason": "spatial_right",
        }
    if re.search(r"\bleft\b", t) and opts:
        return {
            "resolved": True,
            "cancel": False,
            "choice": opts[0],
            "index": 0,
            "reason": "spatial_left",
        }

    # Bare yes only if single option or expected yes_no
    if pending.expected_answer_type == "yes_no" and re.match(
        r"^(?:yes|yeah|yep|that\s+one|ok)\b", t
    ):
        choice = opts[0] if opts else {"label": "yes"}
        return {"resolved": True, "cancel": False, "choice": choice, "reason": "yes"}

    # "yes" with multi-option clarify is NOT a resolution
    if re.match(r"^(?:yes|yeah|yep)\b", t) and len(opts) > 1:
        return None

    return None


def set_confirmation(
    *,
    action: str,
    args: dict[str, Any] | None = None,
    target: str = "",
    risk: str = "",
    task: str = "",
    plan_steps: list[dict[str, Any]] | None = None,
) -> ConfirmationState:
    return ConfirmationState(
        action=action,
        args=dict(args or {}),
        target=target[:120],
        risk=risk,
        task=task[:160],
        plan_steps=list(plan_steps or []),
    )


def resolve_confirmation(text: str, pending: ConfirmationState | None) -> dict[str, Any] | None:
    if pending is None or not pending.is_active():
        return None
    t = (text or "").strip().lower()
    if re.match(r"^(?:yes|yeah|yep|confirm|proceed|ok|okay)\b", t):
        return {
            "authorized": True,
            "action": pending.action,
            "args": dict(pending.args),
            "plan_steps": list(pending.plan_steps),
            "confirmation_id": pending.confirmation_id,
        }
    if re.match(r"^(?:no|cancel|never\s+mind|abort|stop)\b", t):
        return {"authorized": False, "cancel": True, "confirmation_id": pending.confirmation_id}
    # Unrelated utterance — do not authorize
    return None


__all__ = [
    "set_clarification",
    "resolve_clarification",
    "set_confirmation",
    "resolve_confirmation",
]
