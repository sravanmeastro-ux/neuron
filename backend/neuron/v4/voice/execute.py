"""Execute hierarchical voice route through existing AgentLoop only."""

from __future__ import annotations

import logging
import time
from typing import Any

from neuron.v4.voice import canary, commit
from neuron.v4.voice.response import guard_hierarchical_say, outcome_from_loop
from neuron.v4.voice.types import (
    LatencySample,
    RouteDecision,
    RouteKind,
    VoiceRequest,
    note_duplicate_execution,
)

log = logging.getLogger("neuron.v4.voice")


def build_hierarchical_plan(text: str) -> tuple[Any, dict]:
    from neuron.v4.plan import HierarchicalPlanner

    p = HierarchicalPlanner()
    t0 = time.perf_counter()
    plan = p.create_plan(text)
    ms = (time.perf_counter() - t0) * 1000
    return plan, {"plan_ms": ms, "planner": p}


def plan_to_agent_plan(task_plan) -> dict | None:
    if task_plan is None:
        return None
    legacy = task_plan.to_legacy_plan()
    if not legacy.get("steps"):
        return None
    # Normalize tool key for AgentLoop
    steps = []
    for s in legacy["steps"]:
        steps.append({
            "tool": s.get("action") or s.get("tool"),
            "action": s.get("action") or s.get("tool"),
            "arguments": dict(s.get("args") or {}),
            "args": dict(s.get("args") or {}),
            "target": s.get("target") or "",
            "expected_result": s.get("expected_result") or "",
        })
    return {
        "say": legacy.get("say") or "",
        "steps": steps,
        "source": legacy.get("source"),
        "plan_id": legacy.get("plan_id"),
    }


def execute_hierarchical(
    req: VoiceRequest,
    *,
    loop: Any,
    decision: RouteDecision,
    confirmed: bool = False,
    normalized: str = "",
) -> tuple[str | None, bool, dict]:
    """
    Run HierarchicalPlanner → legacy plan → AgentLoop.run.
    Marks route commit on first step; never falls back to full legacy replay after mutation.
    """
    meta: dict[str, Any] = {
        "path": "hierarchical",
        "hierarchical_voice": True,
        "route": decision.to_dict(),
        "request_id": req.request_id,
    }
    lat = LatencySample()
    t0 = time.perf_counter()
    commit.begin_route(req.request_id)

    text = normalized or req.normalized or req.text
    try:
        task_plan, pmeta = build_hierarchical_plan(text)
        lat.plan_ms = float(pmeta.get("plan_ms") or 0)
        meta["v4_plan"] = {
            "plan_id": getattr(task_plan, "plan_id", ""),
            "source": getattr(task_plan, "source", ""),
            "n_subgoals": len(getattr(task_plan, "subgoals", []) or []),
        }
        agent_plan = plan_to_agent_plan(task_plan)
        if not agent_plan or not agent_plan.get("steps"):
            # Before commit — caller may fall back to legacy
            commit.clear_route(req.request_id)
            meta["fallback_allowed"] = True
            meta["reason"] = "empty hierarchical plan"
            return None, False, meta

        # Safety pre-check each step
        try:
            from neuron.safety.policy import allow, risk_of
            for st in agent_plan["steps"]:
                tool = st.get("tool") or st.get("action") or ""
                ok, reason = allow(tool, st.get("arguments") or st.get("args") or {}, confirmed=confirmed)
                risk = risk_of(tool)
                if not ok and "confirm" not in reason.lower() and "blocked" in reason.lower():
                    commit.clear_route(req.request_id)
                    meta["fallback_allowed"] = True
                    meta["reason"] = f"blocked: {reason}"
                    return reason or "Blocked.", True, meta
                meta.setdefault("risks", []).append({"tool": tool, "risk": risk})
        except Exception as exc:
            log.info("[VOICE] safety precheck: %s", exc)

        # Mark commit when we hand plan to AgentLoop (about to mutate)
        first_tool = (agent_plan["steps"][0].get("tool") or "")
        commit.mark_mutation(first_tool or "hierarchical_start", request_id=req.request_id)
        decision.committed = True
        meta["route"] = decision.to_dict()

        say, acted, loop_meta, goal = loop.run(
            request=text,
            context=f"hierarchical_voice request_id={req.request_id}",
            normalized=text,
            plan=agent_plan,
            observe_blob=f"route={decision.route.value}",
            confirmed=confirmed,
        )
        loop_meta = dict(loop_meta or {})
        loop_meta["hierarchical_voice"] = True
        # Infer verify from goal/meta
        if goal is not None and not loop_meta.get("verify_status"):
            st = str(getattr(goal, "status", "") or "").lower()
            if st in ("done", "success", "completed"):
                loop_meta["verify_status"] = "SUCCESS"
            elif st in ("failed", "failure", "error"):
                loop_meta["verify_status"] = "FAILURE"
            elif st in ("uncertain",):
                loop_meta["verify_status"] = "UNCERTAIN"

        outcome = outcome_from_loop(
            say=say,
            acted=acted,
            loop_meta=loop_meta,
            goal=goal,
            needs_confirm=loop_meta.get("needs_confirm"),
            path="hierarchical",
        )
        summary = ""
        if agent_plan["steps"]:
            summary = str(agent_plan["steps"][0].get("tool") or "")
        say2 = guard_hierarchical_say(say, outcome, action_summary=summary)
        lat.total_ms = (time.perf_counter() - t0) * 1000
        meta.update({
            "loop": {k: loop_meta.get(k) for k in (
                "path", "needs_confirm", "recovered", "verify_status", "errors",
            ) if k in loop_meta or True},
            "outcome": outcome.value,
            "latency": lat.to_dict(),
            "fallback_allowed": False,
        })
        meta["loop"] = {
            "path": loop_meta.get("path"),
            "needs_confirm": loop_meta.get("needs_confirm"),
            "recovered": loop_meta.get("recovered"),
            "verify_status": loop_meta.get("verify_status"),
            "errors": loop_meta.get("errors"),
        }
        return say2, acted, meta
    except Exception as exc:
        log.info("[VOICE] hierarchical execute error: %s", exc)
        meta["error"] = str(exc)
        if commit.may_fallback_to_legacy(req.request_id):
            meta["fallback_allowed"] = True
            commit.clear_route(req.request_id)
            return None, False, meta
        # Committed — do not legacy-replay
        note_duplicate_execution()  # would-be duplicate if caller ignores
        meta["fallback_allowed"] = False
        meta["outcome"] = "FAILURE"
        return f"I hit a problem and stopped to avoid repeating the action: {exc}", True, meta
    finally:
        # Keep commit state until clear by caller after finish; clear here if cancelled
        pass


def refuse_legacy_replay_after_commit(request_id: str) -> bool:
    """Return True if legacy replay must be blocked."""
    if commit.is_committed(request_id):
        note_duplicate_execution()
        return True
    return False


__all__ = [
    "build_hierarchical_plan",
    "plan_to_agent_plan",
    "execute_hierarchical",
    "refuse_legacy_replay_after_commit",
]
