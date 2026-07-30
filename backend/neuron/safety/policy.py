"""Risk policy — Phase 8 Safe / Confirmation / High / Blocked tiers."""

from __future__ import annotations

from neuron.safety import levels
from neuron.safety.levels import (
    BLOCKED,
    CONFIRM,
    HIGH,
    SAFE,
    Classification,
    classify,
    normalize_tier,
    tier_prompt,
)

_pending_confirm: dict | None = None


def set_pending(confirm: dict | None) -> None:
    global _pending_confirm
    _pending_confirm = confirm


def get_pending() -> dict | None:
    return _pending_confirm


def clear_pending() -> dict | None:
    global _pending_confirm
    p = _pending_confirm
    _pending_confirm = None
    return p


def risk_of(name: str) -> str:
    """Effective tier for a tool name (no args). Prefer classify() when args exist."""
    return classify(name, {}).tier


def requires_confirm(name: str, args: dict | None = None) -> bool:
    c = classify(name, args)
    return c.tier in (CONFIRM, HIGH)


def is_blocked(name: str, args: dict | None = None) -> bool:
    return classify(name, args).tier == BLOCKED


def allow(name: str, args: dict | None = None, *, confirmed: bool = False) -> tuple[bool, str]:
    """Return (allowed, reason). Blocked never allowed; confirm/high need confirmed=True."""
    args = args or {}
    c = classify(name, args)

    if c.tier == BLOCKED:
        return False, c.reason or f"Blocked: {name}"

    if c.tier == SAFE:
        return True, ""

    if c.tier in (CONFIRM, HIGH):
        if confirmed or bool(args.get("confirmed")):
            # Still refuse blocked-shaped payloads even if somehow labeled confirm
            if levels._BLOCKED_CONTENT.search(levels._blob(args)):
                return False, "Blocked high-consequence content (cannot override with confirm)."
            return True, ""
        label = "High-consequence" if c.tier == HIGH else "Confirmation required"
        detail = c.reason or f"{name} needs your OK"
        return False, f"{label}: {detail}. Say 'confirm' or 'go ahead' to proceed, or 'cancel'."

    return True, ""


def explain(name: str, args: dict | None = None) -> dict:
    c = classify(name, args)
    ok, reason = allow(name, args, confirmed=False)
    return {
        **c.to_dict(),
        "allowed_without_confirm": ok,
        "message": reason or "OK to run",
    }


# Re-exports for callers / tests
__all__ = [
    "SAFE",
    "CONFIRM",
    "HIGH",
    "BLOCKED",
    "Classification",
    "classify",
    "normalize_tier",
    "tier_prompt",
    "risk_of",
    "requires_confirm",
    "is_blocked",
    "allow",
    "explain",
    "set_pending",
    "get_pending",
    "clear_pending",
]
