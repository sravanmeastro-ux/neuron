"""Dynamic planning — insert recovery steps, skip optional, replan remaining."""

from __future__ import annotations

from typing import Any

from neuron.taskplan.types import StepStatus, Subtask, TaskGraph


def apply_correction(sub: Subtask, alt: dict[str, Any]) -> bool:
    """Swap subtask action in-place. Returns True if changed."""
    new_action = str(alt.get("action") or "")
    new_args = dict(alt.get("args") or {})
    if not new_action:
        return False
    if new_action == "wait":
        # Map wait to a no-op friendly tool if missing — use type empty skip via sleep in engine
        sub.action = "get_active_window"  # cheap probe as backoff stand-in
        sub.args = {}
        sub.description = f"(backoff) {sub.description}"
        return True
    sig = f"{sub.action}|{sorted((sub.args or {}).items())}"
    new_sig = f"{new_action}|{sorted(new_args.items())}"
    if sig == new_sig:
        return False
    sub.action = new_action
    if new_args:
        sub.args = new_args
    return True


def insert_recovery_subtask(graph: TaskGraph, after: Subtask, alt: dict[str, Any]) -> Subtask | None:
    """Insert a one-shot recovery node before retrying the failed step."""
    if not alt.get("action"):
        return None
    recovery = Subtask(
        description=f"Recovery: {alt.get('reason') or alt.get('action')}",
        action=str(alt["action"]),
        args=dict(alt.get("args") or {}),
        depends_on=list(after.depends_on or []),
        expected_result=f"Recover toward: {after.description}",
        max_attempts=2,
        use_screen=str(alt.get("action")) == "screen_understand",
    )
    # Failed step now depends on recovery
    after.depends_on = list(set(list(after.depends_on or []) + [recovery.subtask_id]))
    # Insert before `after` in list
    try:
        idx = graph.subtasks.index(after)
        graph.subtasks.insert(idx, recovery)
    except ValueError:
        graph.subtasks.append(recovery)
    return recovery


def skip_optional(sub: Subtask) -> None:
    sub.status = StepStatus.SKIPPED
    sub.last_error = "skipped_after_retries"


def replan_remaining(graph: TaskGraph, *, goal_text: str = "") -> dict[str, Any]:
    """
    Lightweight dynamic replan: for remaining PENDING steps, try rebuild from goal
    only if graph is mostly failed — otherwise keep graph and mark source.
    """
    pending = [s for s in graph.subtasks if s.status in (StepStatus.PENDING, StepStatus.READY, StepStatus.FAILED)]
    completed = [s for s in graph.subtasks if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)]
    if not pending:
        return {"replanned": False, "reason": "nothing_pending"}

    # Soft dynamic plan: ensure open_app exists before UI steps if app known
    apps = list(graph.goal.applications or [])
    changed = 0
    if apps:
        has_open = any(
            s.action == "open_app" and s.status != StepStatus.FAILED
            for s in graph.subtasks
        )
        if not has_open:
            opener = Subtask(
                description=f"Open {apps[0]}",
                action="open_app",
                args={"name": apps[0]},
                expected_result=f"{apps[0]} focused",
                use_fast=True,
            )
            # Make pending UI-ish steps depend on opener
            for s in pending:
                if s.action in ("click_element", "click_ui_element", "type_text", "screen_understand", "browser_click"):
                    s.depends_on = list(set(list(s.depends_on or []) + [opener.subtask_id]))
            graph.subtasks.insert(0, opener)
            changed += 1

    graph.source = f"{graph.source}+dynamic" if "dynamic" not in (graph.source or "") else graph.source
    return {
        "replanned": changed > 0,
        "inserted": changed,
        "pending": len(pending),
        "completed": len(completed),
        "goal": goal_text or graph.goal.text,
    }
