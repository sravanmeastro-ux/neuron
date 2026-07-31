"""Phase 9 — recover from failed steps without restarting the whole goal."""

from __future__ import annotations

from typing import Any

from neuron.brain.goal import GoalState


def deterministic_recovery(
    failed_step: dict,
    error: str,
    goal: GoalState,
    category: str | None = None,
) -> list[dict] | None:
    """
    Try another valid method for the failed step.

    Prefer structured `category` (V3.7) over error-string heuristics.
    Returns replacement steps for the failed step only, or None to replan.
    """
    action = (failed_step.get("action") or "").strip()
    args = dict(failed_step.get("args") or {})
    err = (error or "").lower()
    cat = (category or "").strip().upper()
    tried = {(h.get("action"), str(h.get("args"))) for h in goal.action_history}

    def unused(step: dict) -> bool:
        key = (step.get("action"), str(step.get("args") or {}))
        return key not in tried

    # Terminal / ask-user categories — no deterministic steps
    if cat in ("POLICY_BLOCKED", "INTERRUPTED", "PERMISSION_REQUIRED", "AMBIGUOUS_TARGET"):
        return None

    # --- Category-first recoveries (work for any action) ---
    cat_steps = _recovery_for_category(cat, failed_step, args, unused)
    if cat_steps is not None:
        return cat_steps

    # Fallback: keyword heuristics when category unknown / empty
    if not cat or cat == "UNKNOWN":
        if "popup" in err or "dialog" in err or "cookie" in err or "consent" in err:
            cat_steps = _recovery_for_category("POPUP_DETECTED", failed_step, args, unused)
            if cat_steps:
                return cat_steps
        if "focus" in err or "wrong window" in err or "not focused" in err:
            cat_steps = _recovery_for_category(
                "FOCUS_LOST" if "focus" in err else "WRONG_WINDOW",
                failed_step,
                args,
                unused,
            )
            if cat_steps:
                return cat_steps
        if "monitor" in err or "wrong monitor" in err:
            cat_steps = _recovery_for_category("WRONG_MONITOR", failed_step, args, unused)
            if cat_steps:
                return cat_steps
        if "timeout" in err or "timed out" in err:
            cat_steps = _recovery_for_category("ACTION_TIMEOUT", failed_step, args, unused)
            if cat_steps:
                return cat_steps
        if "page" in err and ("load" in err or "blank" in err):
            cat_steps = _recovery_for_category("PAGE_NOT_LOADED", failed_step, args, unused)
            if cat_steps:
                return cat_steps

    # --- Action-specific alternate methods ---
    alts: list[dict] = []

    if action in ("open_app", "focus_app", "launch_app"):
        name = (args.get("name") or args.get("application") or "").strip()
        if not name:
            return None
        cand = {"action": "focus_app", "args": {"name": name}}
        if unused(cand):
            alts.append(cand)
        cand2 = {
            "action": "open_app",
            "args": {"name": name, "wait_seconds": 20, "auto_learn": True},
        }
        if unused(cand2):
            alts.append(cand2)
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

    if action in ("click_ui_element", "find_ui_element", "click_element", "find_element"):
        name = (args.get("name") or args.get("text") or "").strip()
        if name:
            find = {"action": "find_element", "args": {"name": name}}
            click = {"action": "click_element", "args": {"name": name}}
            if unused(find):
                alts.append(find)
            if unused(click):
                alts.append(click)
            find_u = {"action": "find_ui_element", "args": {"name": name}}
            click_u = {"action": "click_ui_element", "args": {"name": name}}
            if unused(find_u):
                alts.append(find_u)
            if unused(click_u):
                alts.append(click_u)
            return alts[:3] or None

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

    # skip_ad failed (button not ready yet) → wait + retry skip_ad.
    # NEVER recover with page_scroll — that caused the "scrolling up and down" bug.
    if action in ("skip_ad", "youtube.skip_ad", "youtube_skip_ad"):
        wait = {"action": "wait", "args": {"seconds": 2}}
        retry = {
            "action": "skip_ad",
            "args": {},
            "expected_result": "ad skipped or no ad showing",
        }
        out = []
        if unused(wait):
            out.append(wait)
        if unused(retry):
            out.append(retry)
        return out or None

    return None


def _recovery_for_category(
    cat: str,
    failed_step: dict,
    args: dict,
    unused,
) -> list[dict] | None:
    """Structured recovery steps keyed by failure category."""
    name = (
        args.get("name")
        or args.get("title")
        or args.get("app")
        or args.get("application")
        or ""
    )
    name = str(name).strip()

    if cat == "POPUP_DETECTED":
        esc = {"action": "press_keys", "args": {"keys": "esc"}}
        out: list[dict] = []
        if unused(esc):
            out.append(esc)
        out.append(dict(failed_step))
        return out

    if cat in ("FOCUS_LOST", "WRONG_WINDOW"):
        if name:
            cand = {"action": "focus_app", "args": {"name": name}}
            if unused(cand):
                return [cand, dict(failed_step)]
        # Generic: Alt+Tab won't help reliably — wait then retry
        wait = {"action": "wait", "args": {"seconds": 0.5}}
        out = []
        if unused(wait):
            out.append(wait)
        out.append(dict(failed_step))
        return out

    if cat == "WRONG_MONITOR":
        mon = args.get("monitor") or args.get("monitor_id") or "other"
        if name:
            cand = {
                "action": "move_window_to_monitor",
                "args": {"name": name, "monitor": mon},
            }
            if unused(cand):
                return [cand, dict(failed_step)]
        # Same move already attempted — defer to loop same-step retry
        return None

    if cat == "ACTION_TIMEOUT":
        wait = {"action": "wait", "args": {"seconds": 1.5}}
        out = []
        if unused(wait):
            out.append(wait)
        out.append(dict(failed_step))
        return out

    if cat == "PAGE_NOT_LOADED":
        wait = {"action": "wait", "args": {"seconds": 2}}
        out = []
        if unused(wait):
            out.append(wait)
        out.append(dict(failed_step))
        return out

    if cat == "WINDOW_NOT_FOUND":
        if name:
            focus = {"action": "focus_app", "args": {"name": name}}
            open_ = {
                "action": "open_app",
                "args": {"name": name, "wait_seconds": 15, "auto_learn": True},
            }
            out = []
            if unused(focus):
                out.append(focus)
            if unused(open_):
                out.append(open_)
            return out[:2] or None
        return None

    if cat == "APP_NOT_RUNNING":
        if name:
            focus = {"action": "focus_app", "args": {"name": name}}
            open_ = {
                "action": "open_app",
                "args": {"name": name, "wait_seconds": 20, "auto_learn": True},
            }
            out = []
            # Prefer focus (process may already be up), then re-open with longer wait
            if unused(focus):
                out.append(focus)
            if unused(open_):
                out.append(open_)
            return out[:2] or None
        return None

    if cat == "ELEMENT_NOT_FOUND":
        # Let action-specific path below handle click/find alts
        return None

    if cat == "VERIFICATION_FAILED":
        wait = {"action": "wait", "args": {"seconds": 1.0}}
        out = []
        if unused(wait):
            out.append(wait)
        out.append(dict(failed_step))
        return out

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
