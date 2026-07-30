"""Confirmation helpers for WS / voice layer (Phase 8)."""

from __future__ import annotations

from neuron.safety import policy
from neuron.safety.levels import classify


def request_confirm(action: str, args: dict, reason: str = "") -> dict:
    c = classify(action, args)
    payload = {
        "action": action,
        "args": args,
        "reason": reason or c.reason or f"Confirm {action}?",
        "tier": c.tier,
        "prompt": (
            f"{'High-consequence action' if c.tier == 'high' else 'Needs confirmation'}: "
            f"{action}. Say confirm to proceed, or cancel."
        ),
    }
    policy.set_pending(payload)
    return payload


def take_pending() -> dict | None:
    return policy.clear_pending()


def pending_summary() -> str | None:
    p = policy.get_pending()
    if not p:
        return None
    return p.get("prompt") or p.get("reason") or f"Confirm {p.get('action')}?"
