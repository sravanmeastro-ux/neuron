"""Risk assessment for planned tools — confirm before destructive actions."""

from __future__ import annotations

from typing import Any

from neuron.taskplan.types import Subtask, TaskGraph

_DESTRUCTIVE_ACTIONS = frozenset({
    "run_powershell",
    "task_move_files",
    "task_zip_folder",
    "close_app",
    "browser_close_tab",
})

_DESTRUCTIVE_HINTS = (
    "delete", "remove", "uninstall", "format", "wipe", "overwrite",
    "move all", "zip", "install", "rm ", "del ",
)

_SCORE = {"safe": 0, "confirm": 1, "high": 2, "blocked": 3}


def assess_action(action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return risk tier + whether confirmation is required."""
    args = args or {}
    tier = "safe"
    reason = ""
    needs = False
    try:
        from neuron.safety.levels import classify, CONFIRM, HIGH, BLOCKED
        c = classify(action, args)
        tier = str(getattr(c, "tier", None) or c).lower()
        # tier may be enum-like
        if hasattr(c, "tier"):
            tier = str(c.tier).lower()
        reason = str(getattr(c, "reason", "") or "")
        needs = c.tier in (CONFIRM, HIGH, BLOCKED) if hasattr(c, "tier") else tier in (
            "confirm", "high", "blocked"
        )
    except Exception:
        needs = action in _DESTRUCTIVE_ACTIONS
        tier = "confirm" if needs else "safe"

    # Normalize tier string
    for key in ("blocked", "high", "confirm", "safe"):
        if key in tier:
            tier = key
            break
    else:
        tier = "safe"

    blob = f"{action} {args} {reason}".lower()
    destructive = action in _DESTRUCTIVE_ACTIONS or any(h in blob for h in _DESTRUCTIVE_HINTS)
    if destructive and tier == "safe":
        tier = "confirm"
        needs = True
        reason = reason or "Destructive or irreversible action"
    if destructive:
        needs = True
    return {
        "action": action,
        "tier": tier,
        "needs_confirm": bool(needs),
        "destructive": destructive,
        "reason": reason or ("destructive" if destructive else ""),
        "score": _SCORE.get(tier, 1 if destructive else 0),
    }


def assess_plan(graph: TaskGraph) -> dict[str, Any]:
    """Score entire plan; annotate subtasks that require confirmation."""
    items = []
    max_score = 0
    confirm_ids: list[str] = []
    for sub in graph.subtasks:
        info = assess_action(sub.action, sub.args)
        items.append({"subtask_id": sub.subtask_id, "description": sub.description, **info})
        max_score = max(max_score, int(info.get("score") or 0))
        if info.get("needs_confirm") or info.get("destructive"):
            sub.requires_confirm = True
            confirm_ids.append(sub.subtask_id)
    if graph.goal.destructive:
        max_score = max(max_score, 1)
    level = {0: "low", 1: "medium", 2: "high", 3: "blocked"}.get(max_score, "medium")
    return {
        "level": level,
        "max_score": max_score,
        "confirm_required_count": len(confirm_ids),
        "confirm_subtask_ids": confirm_ids,
        "goal_destructive": bool(graph.goal.destructive),
        "items": items,
    }


def must_confirm(sub: Subtask, *, confirmed: bool) -> tuple[bool, str]:
    if confirmed:
        return False, ""
    if sub.requires_confirm:
        return True, f"{sub.action}: {sub.description}"
    info = assess_action(sub.action, sub.args)
    if info.get("needs_confirm") or info.get("destructive"):
        return True, info.get("reason") or f"{sub.action} requires confirmation"
    try:
        from neuron.safety import policy
        ok, reason = policy.allow(sub.action, sub.args or {}, confirmed=False)
        if not ok:
            return True, reason or f"{sub.action} needs confirmation"
    except Exception:
        pass
    return False, ""
