"""Phase 9 — recover from failed steps without restarting the whole goal."""

from __future__ import annotations

from typing import Any

from neuron.brain.goal import GoalState


def deterministic_recovery(
    failed_step: dict,
    error: str,
    goal: GoalState,
) -> list[dict] | None:
    """
    Try another valid method for the failed step.
    Returns replacement steps for the failed step only (not the whole goal),
    or None to fall through to LLM replan.
    """
    action = (failed_step.get("action") or "").strip()
    args = dict(failed_step.get("args") or {})
    err = (error or "").lower()
    tried = {(h.get("action"), str(h.get("args"))) for h in goal.action_history}

    def unused(step: dict) -> bool:
        key = (step.get("action"), str(step.get("args") or {}))
        return key not in tried

    alts: list[dict] = []

    if action in ("open_app", "focus_app"):
        name = (args.get("name") or args.get("application") or "").strip()
        if not name:
            return None
        # 1) Focus if process may already be up
        cand = {"action": "focus_app", "args": {"name": name}}
        if unused(cand):
            alts.append(cand)
        # 2) Re-open with longer wait
        cand2 = {
            "action": "open_app",
            "args": {"name": name, "wait_seconds": 20, "auto_learn": True},
        }
        if unused(cand2):
            alts.append(cand2)
        # 3) Shell Start Menu style via type_text path is too risky — skip
        return alts[:2] or None

    if action in ("browser_click", "browser_find_element"):
        name = (args.get("name") or args.get("text") or "").strip()
        idx = args.get("index")
        if name:
            find = {"action": "browser_find_element", "args": {"name": name}}
            click = {"action": "browser_click", "args": {"name": name}}
            if unused(find):
                alts.append(find)
            if unused(click):
                alts.append(click)
        if idx is not None:
            click_i = {"action": "browser_click", "args": {"index": int(idx)}}
            if unused(click_i):
                alts.append(click_i)
        elif "first" in err or not name:
            alts.append({"action": "browser_click", "args": {"index": 0}})
        return alts[:3] or None

    if action in ("click_ui_element", "find_ui_element"):
        name = (args.get("name") or args.get("text") or "").strip()
        if name:
            find = {"action": "find_ui_element", "args": {"name": name}}
            click = {"action": "click_ui_element", "args": {"name": name}}
            if unused(find):
                alts.append(find)
            if unused(click):
                alts.append(click)
            return alts[:2] or None

    if action in ("browser_open", "open_website"):
        site = (args.get("site") or args.get("url") or args.get("name") or "").strip()
        if site:
            nav = {"action": "browser_navigate", "args": {"url": site}}
            open_ = {"action": "browser_open", "args": {"site": site}}
            if unused(open_):
                alts.append(open_)
            if unused(nav):
                alts.append(nav)
            return alts[:2] or None

    if action in ("browser_search", "search_site"):
        site = (args.get("site") or "google").strip()
        query = (args.get("query") or args.get("q") or "").strip()
        if query:
            alt = {"action": "browser_search", "args": {"site": site, "query": query}}
            if unused(alt):
                return [alt]

    return None


def merge_recovery(
    failed_step: dict,
    remaining_after_failed: list[dict],
    recovery_steps: list[dict],
) -> list[dict]:
    """Replace failed step with recovery attempts, keep later pending steps."""
    # Avoid duplicating the exact failed step at head of recovery
    cleaned = []
    for s in recovery_steps:
        if (s.get("action") == failed_step.get("action")
                and (s.get("args") or {}) == (failed_step.get("args") or {})):
            continue
        cleaned.append(s)
    if not cleaned:
        cleaned = list(recovery_steps)
    return cleaned + list(remaining_after_failed or [])


def llm_replan_pending(
    request: str,
    context: str,
    goal: GoalState,
    failed_step: dict,
    error: str,
    normalized: str = "",
) -> dict | None:
    """Ask planner for remaining steps only, given GoalState."""
    from neuron.brain import planner

    state_blob = (
        "\n\nGOAL_STATE:\n" + goal.compact()
        + "\n\nCOMPLETED_STEPS (do NOT repeat):\n"
        + _steps_blob(goal.completed_steps)
        + "\n\nFAILED_STEP:\n"
        + f"{failed_step}\nError: {error}"
        + "\n\nREPLAN RULES:"
        + "\n- OBSERVE current state, then plan ONLY remaining work."
        + "\n- Do not restart the entire task."
        + "\n- Prefer a different valid method than the failed step."
        + "\n- If unsafe/impossible, empty steps and explain in say."
    )
    return planner.replan(
        request,
        (context or "") + state_blob,
        failed_step,
        error,
        normalized=normalized,
    )


def _steps_blob(steps: list[dict]) -> str:
    if not steps:
        return "(none)"
    lines = []
    for s in steps[-8:]:
        lines.append(f"- {s.get('action')} {s.get('args') or {}}")
    return "\n".join(lines)
