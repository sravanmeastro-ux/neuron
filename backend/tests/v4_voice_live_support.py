"""Shared LIVE validation helpers for V4.10 harnesses.

Mutation only when caller passes live=True. VerificationOutcome is authoritative.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

CFG_PATH = Path(__file__).resolve().parents[1] / "config.json"

# Safe deterministic utterances for canary LIVE (repeated to reach sample counts)
LIVE_POOL = [
    "Open Chrome",
    "Focus Chrome",
    "Move Chrome to monitor 2",
    "Maximize Chrome",
    "Open Notepad",
    "Focus Notepad",
    "Move Chrome to monitor 1",
    "Go to YouTube",
    "Search YouTube for Blender tutorials",
    "Open Chrome",
    "Focus Chrome",
    "Move Chrome to monitor 2",
    "Maximize Chrome",
    "Open Notepad",
    "Focus Notepad",
    "Move Chrome to monitor 1",
    "Go to YouTube",
    "Search YouTube for Unreal Engine tutorials",
    "Open Chrome",
    "Focus Chrome",
    "Move Chrome to monitor 2",
    "Maximize Chrome",
    "Open Notepad",
    "Focus Chrome",
]


def load_agent_cfg() -> dict[str, Any]:
    data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    return dict(data.get("agent") or {})


def set_voice_mode(*, enabled: bool, mode: str, learning: bool = False) -> None:
    data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    agent = dict(data.get("agent") or {})
    agent["hierarchical_voice_enabled"] = bool(enabled)
    agent["voice_routing_mode"] = str(mode).upper()
    agent["procedure_learning_enabled"] = bool(learning)
    data["agent"] = agent
    CFG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def classify_outcome(say: str | None, acted: bool, meta: dict | None) -> str:
    """Map AgentLoop/meta to Verification-oriented outcome label."""
    meta = meta or {}
    if (say or "").strip() == "__STOP_SPEECH__":
        return "CANCELLED"
    goal = meta.get("goal") or {}
    status = str(goal.get("status") or meta.get("outcome") or "").lower()
    verify = str(meta.get("verify_status") or (meta.get("loop") or {}).get("verify_status") or "").upper()
    path = str(meta.get("path") or "")
    if path == "stop" or status in ("interrupted", "cancelled", "canceled"):
        return "CANCELLED"
    if meta.get("needs_confirm") or status in ("needs_confirm",) or path == "confirm_agent_loop" and meta.get("needs_confirm"):
        return "WAITING_FOR_CONFIRMATION"
    if verify == "UNCERTAIN" or status in ("uncertain",) or meta.get("uncertain"):
        return "UNCERTAIN"
    if verify == "FAILURE" or status in ("failed", "failure", "error", "blocked"):
        return "FAILURE"
    if verify == "SUCCESS" or status in ("done", "success", "completed", "ok"):
        return "SUCCESS"
    # Hierarchical path without verify must not invent SUCCESS
    if meta.get("hierarchical_voice") or meta.get("path") == "hierarchical":
        if acted and not meta.get("errors"):
            return "UNCERTAIN"
        return "FAILURE"
    # Legacy path: acted without explicit failure → still not auto SUCCESS for LIVE report
    if acted and status in ("partial_success",):
        return "UNCERTAIN"
    if acted and not goal.get("errors"):
        return "SUCCESS" if status in ("done", "success", "completed") else "UNCERTAIN"
    return "FAILURE" if acted else "FAILURE"


def run_live_utterance(text: str, *, confirmed: bool = False, via_brain: bool = False) -> dict[str, Any]:
    """Execute one utterance through AgentLoop (or brain.handle_command when via_brain)."""
    from neuron.speech import interrupt as interrupt_mod

    interrupt_mod.clear()
    t0 = time.perf_counter()
    if via_brain:
        import brain as brain_mod
        say, acted = brain_mod.handle_command(text)
        meta = {"path": "brain.handle_command", "via_brain": True}
        # Peek confirm pending
        try:
            from neuron.v4.capability.confirm_resume import peek_pending
            if peek_pending():
                meta["needs_confirm"] = peek_pending()
        except Exception:
            pass
        if (say or "") == "__STOP_SPEECH__":
            meta["path"] = "stop"
    else:
        from neuron.brain import agent as agent_mod
        say, acted, meta = agent_mod.run(text, confirmed=confirmed, use_rules_fallback=True)
        meta = dict(meta or {})
    total_ms = (time.perf_counter() - t0) * 1000
    outcome = classify_outcome(say, acted, meta)
    if meta.get("outcome") in (
        "SUCCESS", "FAILURE", "UNCERTAIN", "CANCELLED",
        "WAITING_FOR_CONFIRMATION", "WAITING_FOR_CLARIFICATION",
    ):
        outcome = str(meta["outcome"])
    if (say or "").strip() == "__STOP_SPEECH__":
        outcome = "CANCELLED"
    return {
        "utterance": text,
        "say": (say or "")[:200],
        "acted": bool(acted),
        "path": meta.get("path"),
        "route": (meta.get("route") or {}),
        "hierarchical_voice": bool(meta.get("hierarchical_voice")),
        "outcome": outcome,
        "recovered": bool(meta.get("recovered")),
        "needs_confirm": meta.get("needs_confirm"),
        "elapsed_ms": round(total_ms, 2),
        "goal": meta.get("goal"),
        "latency": meta.get("latency"),
        "request_id": (meta.get("route") or {}).get("request_id") or meta.get("request_id"),
        "via_brain": via_brain,
    }


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "LIVE_ATTEMPT_COUNT": len(rows),
        "LIVE_VERIFIED_SUCCESS_COUNT": sum(1 for r in rows if r.get("outcome") == "SUCCESS"),
        "LIVE_FAILURE_COUNT": sum(1 for r in rows if r.get("outcome") == "FAILURE"),
        "LIVE_UNCERTAIN_COUNT": sum(1 for r in rows if r.get("outcome") == "UNCERTAIN"),
        "LIVE_RECOVERY_COUNT": sum(1 for r in rows if r.get("recovered")),
        "LIVE_CONFIRM_COUNT": sum(1 for r in rows if r.get("outcome") == "WAITING_FOR_CONFIRMATION"),
        "LIVE_CANCELLED_COUNT": sum(1 for r in rows if r.get("outcome") == "CANCELLED"),
        "mean_latency_ms": round(
            sum(float(r.get("elapsed_ms") or 0) for r in rows) / max(1, len(rows)), 2
        ) if rows else 0.0,
    }
