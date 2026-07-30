"""Confirmation helpers for WS layer."""

from __future__ import annotations

from neuron.safety import policy


def request_confirm(action: str, args: dict, reason: str = "") -> dict:
    payload = {"action": action, "args": args, "reason": reason or f"Confirm {action}?"}
    policy.set_pending(payload)
    return payload


def take_pending() -> dict | None:
    return policy.clear_pending()
