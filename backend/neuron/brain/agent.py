"""NEURON Brain — agent entry.

Phase 9 loop:
  OBSERVE → UNDERSTAND GOAL → PLAN → ACT → OBSERVE RESULT → VERIFY → SUCCESS or RECOVER
"""

from __future__ import annotations

import time
from typing import Any

from neuron.brain import context as ctx_mod
from neuron.brain import intent as intent_mod
from neuron.brain import loop as opavr
from neuron.brain import tool_registry
from neuron.brain.normalize import normalize_plan
from neuron.brain.trace import Trace


def _agent_cfg() -> dict:
    try:
        from pathlib import Path
        import json as _json
        cfg = _json.loads((Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8"))
        return cfg.get("agent") or {}
    except Exception:
        return {}


def _log(msg: str) -> None:
    print(f"[agent] {msg}", flush=True)


def run(
    raw: str,
    *,
    confirmed: bool = False,
    use_rules_fallback: bool = True,
    screen_ctx: str = "",
) -> tuple[str | None, bool, dict]:
    """
    Full brain loop.

    Returns (reply, acted, meta).
    meta.path: recipe | deterministic | llm | opavr | ask_user | rules_fallback | empty | stop
    """
    meta: dict[str, Any] = {
        "path": "",
        "needs_confirm": None,
        "steps": [],
        "replanned": False,
        "recovered": False,
        "elapsed_ms": 0,
        "trace": [],
        "goal": None,
    }
    t0 = time.time()
    tool_registry.ensure_bootstrapped()
    tr = Trace()

    intent = intent_mod.understand(raw)
    _log(f"intent kind={intent.kind} action={intent.action!r} text={intent.normalized!r}")

    if intent.kind == "empty":
        meta["path"] = "empty"
        return None, False, meta
    if intent.kind == "stop":
        meta["path"] = "stop"
        return "__STOP_SPEECH__", True, meta

    # Fast path: known recipe / trivial open — still through OPAVR (verify required)
    if intent.kind in ("recipe", "deterministic") and intent.action:
        meta["path"] = intent.kind
        plan = normalize_plan({
            "say": "",
            "steps": [{"tool": intent.action, "arguments": intent.args or {}}],
        })
        say, acted, loop_meta, goal = opavr.run_opavr(
            request=raw,
            context="",
            normalized=intent.normalized or raw,
            plan=plan,
            confirmed=confirmed,
            observe_blob=f"intent={intent.kind} action={intent.action}",
            trace=tr,
        )
        return _finish(say, acted, meta, loop_meta, goal, tr, t0, path=intent.kind)

    # LLM planner path (+ Phase 8 context)
    meta["path"] = "llm"

    from neuron.brain import resolver as resolver_mod
    from neuron.brain.snapshot import enrich_snapshot, gather_snapshot

    plan_text = intent.normalized or raw
    snap = gather_snapshot(plan_text, deep=False)
    resolve = resolver_mod.resolve(raw, snap)
    if resolve.ambiguous and resolve.band == "low" and intent.normalized:
        resolve2 = resolver_mod.resolve(intent.normalized, snap)
        if resolve2.confidence > resolve.confidence:
            resolve = resolve2

    if resolve.ambiguous and resolve.needs_inspect and resolve.band == "medium":
        _log("context medium confidence -> enrich snapshot")
        snap = enrich_snapshot(snap, plan_text)
        resolve = resolver_mod.resolve(raw, snap)
        if intent.normalized and intent.normalized.strip() != (raw or "").strip():
            resolve2 = resolver_mod.resolve(intent.normalized, snap)
            if resolve2.confidence > resolve.confidence:
                resolve = resolve2

    meta["context_scene"] = snap.scene
    meta["resolve"] = {
        "ambiguous": resolve.ambiguous,
        "confidence": resolve.confidence,
        "band": resolve.band,
        "rewritten": resolve.rewritten_request,
        "ask_user": resolve.ask_user,
        "destructive_blocked": resolve.destructive_blocked,
    }

    if resolve.ambiguous and (
        resolve.band == "low"
        or resolve.destructive_blocked
        or (resolve.ask_user and resolve.confidence < resolver_mod.MEDIUM)
    ):
        meta["path"] = "ask_user"
        meta["elapsed_ms"] = int((time.time() - t0) * 1000)
        say = resolve.ask_user or "Which one did you mean?"
        tr.user(raw)
        tr.final("ask_user", say)
        meta["trace"] = tr.to_list()
        _log(f"ask_user conf={resolve.confidence:.2f}: {say!r}")
        try:
            import memory
            memory.log("neuron", say)
        except Exception:
            pass
        return say, True, meta

    context = ctx_mod.gather(plan_text, snapshot=snap)
    if resolve.ambiguous and resolve.resolved_blob:
        context = (context + "\n\nRESOLVED_REFERENCES:\n" + resolve.resolved_blob).strip()
    if screen_ctx:
        blob = screen_ctx if len(screen_ctx) <= 2200 else screen_ctx[:2200] + "\n…"
        context = (context + "\n\nLIVE SCREENS:\n" + blob).strip()

    plan_request = raw
    plan_normalized = intent.normalized
    if resolve.ambiguous and resolve.band == "high" and resolve.rewritten_request:
        plan_request = resolve.rewritten_request
        plan_normalized = resolve.rewritten_request
        _log(f"resolved -> {plan_request!r} (conf={resolve.confidence:.2f})")

    # OPAVR: plan inside loop (or rules fallback if planner down)
    say, acted, loop_meta, goal = opavr.run_opavr(
        request=plan_request,
        context=context,
        normalized=plan_normalized,
        plan=None,
        confirmed=confirmed,
        observe_blob=snap.compact(600),
        trace=tr,
    )

    if say is None and not acted and loop_meta.get("path") == "plan_failed":
        if use_rules_fallback:
            meta["path"] = "rules_fallback"
            meta["elapsed_ms"] = int((time.time() - t0) * 1000)
            meta["trace"] = tr.to_list()
            _log("planner unavailable -> rules_fallback")
            return None, False, meta
        meta["elapsed_ms"] = int((time.time() - t0) * 1000)
        meta["trace"] = tr.to_list()
        return "My local planner (Ollama) isn't available.", True, meta

    return _finish(say, acted, meta, loop_meta, goal, tr, t0, path="llm")


def _finish(
    say: str | None,
    acted: bool,
    meta: dict,
    loop_meta: dict,
    goal,
    tr: Trace,
    t0: float,
    *,
    path: str,
) -> tuple[str | None, bool, dict]:
    meta["path"] = path
    meta["replanned"] = bool(loop_meta.get("replanned"))
    meta["recovered"] = bool(loop_meta.get("recovered"))
    meta["steps"] = loop_meta.get("steps") or []
    meta["trace"] = tr.to_list()
    meta["elapsed_ms"] = int((time.time() - t0) * 1000)
    if goal is not None:
        meta["goal"] = {
            "goal": goal.goal,
            "status": goal.status,
            "completed": len(goal.completed_steps),
            "pending": len(goal.pending_steps),
            "retries": goal.retry_count,
            "errors": list(goal.errors[-5:]),
        }

    if loop_meta.get("needs_confirm"):
        meta["needs_confirm"] = loop_meta["needs_confirm"]
        from neuron.safety import confirm as confirm_mod
        confirm_mod.request_confirm(
            loop_meta["needs_confirm"]["action"],
            loop_meta["needs_confirm"].get("args") or {},
            loop_meta["needs_confirm"].get("reason") or "",
        )
        say = (
            f"Confirm to run {loop_meta['needs_confirm'].get('action')}: "
            f"{loop_meta['needs_confirm'].get('reason')}. Say 'confirm' to proceed."
        )
        _log(f"done confirm path ({meta['elapsed_ms']}ms)")
        try:
            import memory
            memory.log("neuron", say)
        except Exception:
            pass
        return say, True, meta

    # Never pretend success if goal failed
    if goal is not None and goal.status == "failed":
        say = say or goal.honest_failure_message()
        acted = True

    _log(
        f"done path={meta.get('path')} status={getattr(goal, 'status', '?')} "
        f"acted={acted} ({meta['elapsed_ms']}ms) say={say!r}"[:220]
    )
    try:
        import memory
        if say:
            memory.log("neuron", say)
    except Exception:
        pass
    return say or None, acted, meta


def run_legacy_llm(raw: str, normalized: str = "", screen_ctx: str = "") -> tuple[str | None, bool]:
    """Compatibility wrapper used by brain._run_with_llm."""
    say, acted, _meta = run(
        raw,
        use_rules_fallback=False,
        screen_ctx=screen_ctx,
    )
    if say is None and not acted:
        say, acted, _ = run(normalized or raw, use_rules_fallback=False, screen_ctx=screen_ctx)
    return say, acted
