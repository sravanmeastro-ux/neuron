"""Confirmation resume through AgentLoop (not bare executor)."""

from __future__ import annotations

import time
from typing import Any

CONFIRM_TTL_S = 90.0


def _stamp_pending(payload: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    payload = dict(payload)
    payload.setdefault("at", now)
    payload.setdefault("expires_at", now + CONFIRM_TTL_S)
    payload.setdefault("confirmation_id", f"cfm_{int(now)}")
    return payload


def request_confirm_scoped(
    action: str,
    args: dict[str, Any],
    *,
    reason: str = "",
    task: str = "",
    world_fingerprint: str = "",
) -> dict[str, Any]:
    from neuron.safety import confirm as confirm_mod
    from neuron.v4.context import get_conversation_engine
    from neuron.v4.context.clarify import set_confirmation

    payload = confirm_mod.request_confirm(action, args, reason=reason)
    payload = _stamp_pending(payload)
    payload["task"] = task[:160]
    payload["world_fingerprint"] = world_fingerprint[:64]
    # Re-set stamped pending
    from neuron.safety import policy
    policy.set_pending(payload)

    get_conversation_engine().set_pending_confirmation(
        set_confirmation(
            action=action,
            args=args,
            target=str(args.get("name") or args.get("path") or ""),
            risk=str(payload.get("tier") or ""),
            task=task,
            plan_steps=[{"action": action, "args": dict(args)}],
        )
    )
    return payload


def peek_pending() -> dict[str, Any] | None:
    from neuron.safety import policy

    p = policy.get_pending()
    if not p:
        return None
    if _is_expired(p):
        policy.clear_pending()
        return None
    return p


def _is_expired(pending: dict[str, Any]) -> bool:
    exp = float(pending.get("expires_at") or 0)
    if exp and time.time() > exp:
        return True
    return False


def invalidate_if_stale(*, world_fingerprint: str = "", cancel: bool = False) -> bool:
    """Clear pending if cancelled or world fingerprint changed materially."""
    from neuron.safety import policy

    p = policy.get_pending()
    if not p:
        return False
    if cancel or _is_expired(p):
        policy.clear_pending()
        try:
            from neuron.v4.context import get_conversation_engine
            get_conversation_engine().state.pending_confirmation = None
        except Exception:
            pass
        return True
    prior = str(p.get("world_fingerprint") or "")
    if prior and world_fingerprint and prior != world_fingerprint:
        policy.clear_pending()
        try:
            from neuron.v4.context import get_conversation_engine
            get_conversation_engine().state.pending_confirmation = None
        except Exception:
            pass
        return True
    return False


def resume_confirmation_via_agent_loop(
    *,
    confirmed: bool = True,
) -> tuple[str, bool, dict[str, Any]]:
    """
    User said yes/confirm — resume EXACT pending action through AgentLoop.
    Never calls executor.execute_plan directly.
    """
    from neuron.safety import policy
    from neuron.brain.agent_loop import AgentLoop
    from neuron.brain.normalize import normalize_plan

    pending = policy.get_pending()
    if not pending:
        return "Nothing waiting for confirmation.", True, {"path": "confirm", "empty": True}
    if _is_expired(pending):
        policy.clear_pending()
        return "That confirmation expired. Please ask again.", True, {"path": "confirm", "expired": True}

    action = str(pending.get("action") or "")
    args = dict(pending.get("args") or {})
    if not action:
        policy.clear_pending()
        return "Nothing waiting for confirmation.", True, {"path": "confirm", "empty": True}

    # Clear pending before execute so retries don't double-fire
    policy.clear_pending()
    try:
        from neuron.v4.context import get_conversation_engine
        get_conversation_engine().state.pending_confirmation = None
    except Exception:
        pass

    if not confirmed:
        return "Cancelled.", True, {"path": "confirm", "cancelled": True}

    args = dict(args)
    args["confirmed"] = True
    plan = normalize_plan({
        "say": "",
        "steps": [{"action": action, "args": args}],
    })
    loop = AgentLoop(confirmed=True)
    say, acted, meta, goal = loop.run(
        request=f"confirm {action}",
        context="",
        normalized=f"confirm {action}",
        plan=plan,
        observe_blob=f"confirm_resume action={action}",
        confirmed=True,
    )
    meta = dict(meta or {})
    meta["path"] = "confirm_agent_loop"
    meta["confirm_resume"] = True
    meta["confirmed_action"] = action
    status = getattr(goal, "status", None) if goal is not None else None
    if say is None:
        say = "Done." if status == "success" else "Finished confirmation path."
    return str(say), bool(acted), meta


def cancel_confirmation() -> bool:
    from neuron.safety import policy

    had = policy.clear_pending() is not None
    try:
        from neuron.v4.context import get_conversation_engine
        get_conversation_engine().state.pending_confirmation = None
    except Exception:
        pass
    return had


__all__ = [
    "CONFIRM_TTL_S",
    "request_confirm_scoped",
    "peek_pending",
    "invalidate_if_stale",
    "resume_confirmation_via_agent_loop",
    "cancel_confirmation",
]
