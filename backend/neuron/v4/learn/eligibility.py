"""Eligibility: learn only from VERIFIED SUCCESS traces."""

from __future__ import annotations

from neuron.v4.learn.types import (
    MIN_STEPS_FOR_PROCEDURE,
    TraceStep,
    VerifiedTaskTrace,
)


def is_eligible(trace: VerifiedTaskTrace) -> tuple[bool, str]:
    if trace is None:
        return False, "empty trace"
    if trace.cancelled:
        return False, "cancelled"
    if trace.blocked:
        return False, "blocked"
    if not trace.safety_ok:
        return False, "safety not ok"
    status = (trace.final_status or "").upper()
    if status != "SUCCESS":
        return False, f"final_status={status or 'missing'}"
    if not trace.task_verified:
        return False, "task not verified"
    if not trace.steps:
        return False, "incomplete: no steps"
    if len(trace.steps) < MIN_STEPS_FOR_PROCEDURE:
        return False, "trivial single-step (atomic capability preferred)"

    for i, st in enumerate(trace.steps):
        v = (st.verification or "").upper()
        if v == "FAILURE":
            return False, f"step {i} FAILURE"
        if v == "UNCERTAIN":
            return False, f"step {i} UNCERTAIN (not proven)"
        if v and v != "SUCCESS":
            return False, f"step {i} status={v}"
        if not v:
            return False, f"step {i} missing verification"
        if not (st.tool or st.capability_id):
            return False, f"step {i} missing capability/tool"

    return True, "eligible"


def build_trace(
    *,
    goal_text: str,
    steps: list[dict] | list[TraceStep],
    final_status: str,
    task_verified: bool = False,
    cancelled: bool = False,
    blocked: bool = False,
    safety_ok: bool = True,
    intent_family: str = "",
) -> VerifiedTaskTrace:
    out_steps: list[TraceStep] = []
    for s in steps:
        if isinstance(s, TraceStep):
            out_steps.append(s)
        else:
            out_steps.append(
                TraceStep(
                    capability_id=str(s.get("capability_id") or ""),
                    tool=str(s.get("tool") or s.get("action") or ""),
                    arguments=dict(s.get("arguments") or s.get("args") or {}),
                    verification=str(s.get("verification") or s.get("status") or ""),
                    recovery_used=bool(s.get("recovery_used")),
                    expected_result=str(s.get("expected_result") or ""),
                )
            )
    return VerifiedTaskTrace(
        goal_text=goal_text,
        intent_family=intent_family or _infer_intent(goal_text, out_steps),
        steps=out_steps,
        final_status=final_status,
        task_verified=task_verified,
        cancelled=cancelled,
        blocked=blocked,
        safety_ok=safety_ok,
    )


def _infer_intent(goal: str, steps: list[TraceStep]) -> str:
    g = (goal or "").lower()
    tools = " ".join((s.tool or s.capability_id or "").lower() for s in steps)
    if "youtube" in g or "youtube" in tools or "search" in tools:
        if "play" in g or "play" in tools:
            return "youtube_search_play"
        return "youtube_search"
    if "monitor" in g or "move" in tools:
        return "window_monitor_workflow"
    if "blender" in g or "blender" in tools:
        return "blender_workflow"
    return "multi_step_workflow"


__all__ = ["is_eligible", "build_trace"]
