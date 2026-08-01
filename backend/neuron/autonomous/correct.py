"""Self-correction — diagnose failures and propose alternate actions."""

from __future__ import annotations

from typing import Any

from neuron.taskplan.types import Subtask


def diagnose(sub: Subtask, error: str) -> dict[str, Any]:
    err = (error or "").lower()
    category = "unknown"
    if "confirm" in err:
        category = "needs_confirm"
    elif "timeout" in err or "timed out" in err:
        category = "timeout"
    elif "click" in err or "element" in err or "uia" in err:
        category = "ui_target"
    elif "not found" in err or "unknown tool" in err:
        category = "missing_tool"
    elif "focus" in err or "window" in err or "foreground" in err:
        category = "focus"
    elif "network" in err or "offline" in err or "dns" in err:
        category = "network"
    elif "permission" in err or "denied" in err or "access" in err:
        category = "permission"
    elif "fail" in err or "error" in err:
        category = "execution"
    return {
        "category": category,
        "action": sub.action,
        "error": (error or "")[:300],
        "attempt": sub.attempt_count,
    }


def suggest_corrections(sub: Subtask, error: str) -> list[dict[str, Any]]:
    """Return alternate {action, args, reason} list — prefers existing recover module."""
    diag = diagnose(sub, error)
    alts: list[dict[str, Any]] = []

    try:
        from neuron.brain.goal import GoalState
        from neuron.brain import recover as recover_mod
        goal = GoalState(goal=sub.description)
        goal.action_history.append({
            "action": sub.action,
            "args": dict(sub.args or {}),
            "ok": False,
            "out": error,
        })
        for a in recover_mod.deterministic_recovery(
            {"action": sub.action, "args": dict(sub.args or {})},
            error,
            goal,
        ) or []:
            alts.append({**a, "reason": "deterministic_recovery", "diagnosis": diag["category"]})
    except Exception:
        pass

    # Category-specific ladders (compose Screen / focus / CU-style)
    cat = diag["category"]
    name = str((sub.args or {}).get("name") or (sub.args or {}).get("app") or sub.target or "")
    if cat == "focus" and name:
        alts.append({"action": "focus_app", "args": {"name": name}, "reason": "refocus", "diagnosis": cat})
        alts.append({"action": "open_app", "args": {"name": name}, "reason": "reopen", "diagnosis": cat})
    if cat == "ui_target":
        req = str((sub.args or {}).get("request") or (sub.args or {}).get("name") or sub.description)
        alts.append({
            "action": "screen_understand",
            "args": {"request": req},
            "reason": "screen_fallback",
            "diagnosis": cat,
        })
        if (sub.args or {}).get("name"):
            alts.append({
                "action": "click_ui_element",
                "args": {"name": sub.args["name"]},
                "reason": "uia_retry",
                "diagnosis": cat,
            })
    if cat == "timeout":
        alts.append({"action": "wait", "args": {"seconds": 2}, "reason": "backoff", "diagnosis": cat})
        alts.append({**{"action": sub.action, "args": dict(sub.args or {})}, "reason": "retry_same", "diagnosis": cat})

    # Deduplicate by action+args
    seen = set()
    out = []
    for a in alts:
        sig = f"{a.get('action')}|{sorted((a.get('args') or {}).items())}"
        if sig in seen or not a.get("action"):
            continue
        seen.add(sig)
        out.append(a)
    return out
