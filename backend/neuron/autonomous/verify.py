"""Step and goal verification for autonomous execution."""

from __future__ import annotations

import re
from typing import Any

from neuron.taskplan.types import GoalSpec, Observation, Subtask


def verify_step(
    sub: Subtask,
    *,
    before: Observation | None,
    after: Observation | None,
    ok_flag: bool,
    message: str = "",
) -> dict[str, Any]:
    """Soft verification after a subtask — do not hard-fail on weak signals."""
    reasons: list[str] = []
    score = 0.0

    if ok_flag:
        score += 0.5
        reasons.append("executor_ok")
    else:
        reasons.append("executor_failed")

    exp = (sub.expected_result or sub.description or "").lower()
    msg = (message or "").lower()
    if exp and any(w in msg for w in re.findall(r"[a-z]{4,}", exp)[:6]):
        score += 0.2
        reasons.append("message_matches_expected")

    if before and after:
        if after.application and after.application != before.application:
            score += 0.15
            reasons.append("app_changed")
        if after.window_title and after.window_title != before.window_title:
            score += 0.15
            reasons.append("window_changed")
        # Focus target app if specified
        target = (sub.target or "").lower()
        if target and after.application and target in after.application.lower():
            score += 0.1
            reasons.append("target_app_focused")

    # open_app / focus: require some window signal when available
    if sub.action in ("open_app", "focus_app") and after and after.application:
        score = max(score, 0.6)
        reasons.append("app_present")

    passed = ok_flag and score >= 0.45
    # If executor said ok but soft score weak, still pass (soft)
    if ok_flag and score < 0.45:
        passed = True
        reasons.append("soft_pass_executor_ok")
    return {
        "passed": passed,
        "score": round(score, 3),
        "reasons": reasons,
        "subtask_id": sub.subtask_id,
    }


def verify_goal(
    goal: GoalSpec,
    *,
    steps_completed: int,
    steps_total: int,
    observations: list[Observation] | None = None,
    success_flag: bool = False,
) -> dict[str, Any]:
    """Check completion criteria heuristically."""
    criteria = list(goal.completion_criteria or []) or ["all planned subtasks completed"]
    hits: list[str] = []
    misses: list[str] = []
    obs_blob = " ".join(
        f"{o.application} {o.window_title} {o.notes}" for o in (observations or [])
    ).lower()

    for c in criteria:
        cl = c.lower()
        ok_c = False
        if "all planned" in cl or "subtasks completed" in cl:
            ok_c = steps_total > 0 and steps_completed >= steps_total
        elif "install" in cl:
            ok_c = "install" in obs_blob or steps_completed >= max(1, steps_total - 1)
        elif "zip" in cl:
            ok_c = "zip" in obs_blob or steps_completed >= steps_total
        elif "playing" in cl or "media" in cl:
            ok_c = steps_completed >= steps_total or "youtube" in obs_blob or "chrome" in obs_blob
        elif "hello world" in cl:
            ok_c = steps_completed >= max(1, steps_total - 1)
        elif "archiv" in cl:
            ok_c = steps_completed >= steps_total
        else:
            # keyword overlap with observations or completion ratio
            words = [w for w in re.findall(r"[a-z]{4,}", cl) if w not in ("with", "that", "this", "from")]
            ok_c = (not words) or any(w in obs_blob for w in words) or (
                steps_total > 0 and steps_completed / steps_total >= 0.8
            )
        (hits if ok_c else misses).append(c)

    ratio = steps_completed / max(1, steps_total)
    passed = success_flag or (not misses and ratio >= 1.0) or (ratio >= 0.8 and len(misses) <= 1)
    return {
        "passed": passed,
        "criteria_hit": hits,
        "criteria_miss": misses,
        "completion_ratio": round(ratio, 3),
        "steps_completed": steps_completed,
        "steps_total": steps_total,
    }
