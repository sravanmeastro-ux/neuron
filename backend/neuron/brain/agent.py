"""NEURON Brain — agent entry.

Closed-loop (AgentLoop / OPAVR):
  OBSERVE → UNDERSTAND GOAL → PLAN → ACT (one step) → OBSERVE → VERIFY
  → SUCCESS or RETRY/REPLAN → verify final goal before finish

All execution goes through neuron.brain.agent_loop.AgentLoop.
"""

from __future__ import annotations

import time
from typing import Any

from neuron.brain import context as ctx_mod
from neuron.brain import intent as intent_mod
from neuron.brain import tool_registry
from neuron.brain.agent_loop import AgentLoop
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
    try:
        from neuron.perf import log
        log("agent", msg, level="INFO")
    except Exception:
        print(f"[agent] {msg}", flush=True)


def run(
    raw: str,
    *,
    confirmed: bool = False,
    use_rules_fallback: bool = True,
    screen_ctx: str = "",
) -> tuple[str | None, bool, dict]:
    """
    Full brain loop via AgentLoop.

    Returns (reply, acted, meta).
    meta.path: capability | recipe | deterministic | llm | opavr | ask_user | rules_fallback | empty | stop
    """
    try:
        from neuron.self_healing.watchdog import tick_main_heartbeat
        tick_main_heartbeat()
    except Exception:
        pass
    meta: dict[str, Any] = {
        "path": "",
        "needs_confirm": None,
        "steps": [],
        "replanned": False,
        "recovered": False,
        "elapsed_ms": 0,
        "trace": [],
        "goal": None,
        "agent_loop": True,
    }
    t0 = time.time()
    tool_registry.ensure_bootstrapped()
    tr = Trace()
    loop = AgentLoop(confirmed=confirmed, trace=tr)

    # Personality mode switches ("switch to professional mode")
    try:
        from neuron.personality import maybe_handle_mode_command
        pmc = maybe_handle_mode_command(raw)
        if pmc is not None:
            say, acted, pmeta = pmc
            meta.update(pmeta or {})
            meta["elapsed_ms"] = int((time.time() - t0) * 1000)
            tr.user(raw)
            tr.final("personality", say or "")
            meta["trace"] = tr.to_list()
            return say, acted, meta
    except Exception as exc:
        _log(f"personality mode cmd skipped: {exc}")

    # V4.7 ConversationEngine — shared context/NLU boundary (does not replace routing yet)
    v4u = None
    try:
        from neuron.v4.context import understand_for_agent, on_ask_user_clarify, cancel_for_stop
        from neuron.v4.context.types import RouteDest, ContinuityKind

        v4u = understand_for_agent(raw)
        meta["v4_nlu"] = v4u.to_dict()
        if v4u.route is RouteDest.STOP or v4u.continuity is ContinuityKind.CANCEL:
            if "stop" in (v4u.rewritten_command or raw or "").lower() or (
                v4u.goal and v4u.goal.intent_family.value == "STOP"
            ):
                cancel_for_stop()
                meta["path"] = "stop"
                return "__STOP_SPEECH__", True, meta
        if v4u.route is RouteDest.REJECT:
            meta["path"] = "rejected"
            say = "Okay, I won't."
            return say, True, meta
        if v4u.route is RouteDest.CLARIFY and v4u.clarification:
            on_ask_user_clarify(
                v4u.clarification.prompt,
                original_goal=v4u.rewritten_command or raw,
                options=v4u.clarification.options,
                source="v4_context",
            )
            meta["path"] = "ask_user"
            meta["elapsed_ms"] = int((time.time() - t0) * 1000)
            return v4u.clarification.prompt or "Which one did you mean?", True, meta
        if v4u.clarification_resolution and not v4u.clarification_resolution.get("resolved"):
            if v4u.clarification_resolution.get("cancel"):
                meta["path"] = "ask_user"
                return "Okay, cancelled.", True, meta
            if v4u.clarification_resolution.get("reason") == "neither":
                meta["path"] = "ask_user"
                return "Okay — which one instead?", True, meta
    except Exception as exc:
        _log(f"v4 context skipped: {exc}")

    intent = intent_mod.understand(
        (v4u.rewritten_command if v4u and v4u.rewritten_command else None) or raw
    )
    _log(f"intent kind={intent.kind} action={intent.action!r} text={intent.normalized!r}")

    if intent.kind == "empty":
        meta["path"] = "empty"
        return None, False, meta
    if intent.kind == "stop":
        try:
            from neuron.v4.context import cancel_for_stop
            cancel_for_stop()
        except Exception:
            pass
        meta["path"] = "stop"
        return "__STOP_SPEECH__", True, meta

    cfg = _agent_cfg()

    # Prefer V4.7 rewritten command for downstream resolver/router
    if v4u and v4u.rewritten_command and v4u.confidence >= 0.55:
        raw_for_resolve = v4u.rewritten_command
    else:
        raw_for_resolve = raw

    # V3.3 ReferenceResolver — rewrite deixis using ContextEngine before routing.
    # V3.4: PerceptionEngine supplies ui_candidates only when context is insufficient.
    resolved_request = raw_for_resolve
    if cfg.get("reference_resolver", True):
        try:
            from neuron.v3.reference_resolver import needs_resolution, resolve_reference
            if needs_resolution(intent.normalized or raw_for_resolve) or needs_resolution(raw_for_resolve):
                ref = resolve_reference(raw_for_resolve, intent=intent)
                if (
                    cfg.get("perception_engine", True)
                    and (
                        ref.needs_clarification
                        or ref.confidence < 0.55
                        or ref.evidence in ("ordinal_no_context", "unresolved")
                    )
                ):
                    try:
                        from neuron.v3.perception_engine import (
                            ui_candidates_for,
                            wants_ui_candidates,
                        )
                        probe = (
                            raw_for_resolve
                            if needs_resolution(raw_for_resolve)
                            else (intent.normalized or raw_for_resolve)
                        )
                        if wants_ui_candidates(probe):
                            ui_candidates = ui_candidates_for(probe) or None
                            if ui_candidates:
                                meta["perception_candidates"] = len(ui_candidates)
                                ref = resolve_reference(
                                    raw_for_resolve,
                                    intent=intent,
                                    ui_candidates=ui_candidates,
                                )
                    except Exception as pe_exc:
                        _log(f"perception candidates skipped: {pe_exc}")
                meta["reference"] = ref.to_dict()
                if ref.needs_clarification:
                    meta["path"] = "ask_user"
                    meta["elapsed_ms"] = int((time.time() - t0) * 1000)
                    say = ref.clarification_prompt or "Which one did you mean?"
                    try:
                        from neuron.v4.context import on_ask_user_clarify
                        on_ask_user_clarify(
                            say,
                            original_goal=raw_for_resolve,
                            options=list(getattr(ref, "candidates", None) or [])
                            if isinstance(getattr(ref, "candidates", None), list)
                            else None,
                            source="reference_resolver",
                        )
                    except Exception:
                        pass
                    tr.user(raw)
                    tr.final("ask_user", say)
                    meta["trace"] = tr.to_list()
                    _log(f"reference clarify conf={ref.confidence:.2f}: {say!r}")
                    try:
                        import memory
                        memory.log("neuron", say)
                    except Exception:
                        pass
                    return say, True, meta
                if ref.rewritten_command and ref.confidence >= 0.55:
                    resolved_request = ref.rewritten_command
                    intent = intent_mod.understand(resolved_request)
                    _log(
                        f"reference resolved -> {resolved_request!r} "
                        f"({ref.target_type}/{ref.resolved_target}) "
                        f"conf={ref.confidence:.2f} src={ref.source}"
                    )
        except Exception as exc:
            _log(f"reference_resolver skipped: {exc}")

    # V4.10 hierarchical voice canary / shadow (default LEGACY → no-op)
    try:
        from neuron.v4.voice import maybe_handle_voice
        hv = maybe_handle_voice(
            raw,
            normalized=resolved_request,
            loop=loop,
            intent=intent,
            v4u=v4u,
            confirmed=confirmed,
        )
        if hv is not None:
            say, acted, hmeta = hv
            meta.update({k: v for k, v in (hmeta or {}).items() if k != "loop"})
            loop_meta = dict((hmeta or {}).get("loop") or {})
            if (hmeta or {}).get("outcome"):
                meta["outcome"] = hmeta["outcome"]
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((hmeta or {}).get("path") or "hierarchical"),
            )
    except Exception as exc:
        _log(f"v4 hierarchical voice skipped: {exc}")

    # Task Planning Engine — multi-step workflows (composes AgentLoop / tools / screen)
    # Does not modify FastIntentRouter, Semantic Understanding, or Screen Understanding.
    try:
        from neuron.taskplan import maybe_handle_taskplan
        tp = maybe_handle_taskplan(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if tp is not None:
            say, acted, tmeta = tp
            meta.update({k: v for k, v in (tmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (tmeta or {}).get("needs_confirm"),
                "recovered": bool((tmeta or {}).get("recovered")),
                "steps": (((tmeta or {}).get("report") or {}).get("subtasks") or []),
            }
            tr.user(raw)
            tr.final("taskplan", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((tmeta or {}).get("path") or "taskplan"),
            )
    except Exception as exc:
        _log(f"taskplan skipped: {exc}")

    # Computer Use Agent — operate any app (composes screen / taskplan / vision)
    try:
        from neuron.computer_use import maybe_handle_computer_use
        cu = maybe_handle_computer_use(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if cu is not None:
            say, acted, cmeta = cu
            meta.update({k: v for k, v in (cmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (cmeta or {}).get("needs_confirm"),
                "recovered": bool((cmeta or {}).get("recovered")),
                "steps": (((cmeta or {}).get("report") or {}).get("actions") or []),
            }
            tr.user(raw)
            tr.final("computer_use", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((cmeta or {}).get("path") or "computer_use"),
            )
    except Exception as exc:
        _log(f"computer_use skipped: {exc}")

    # Multi-Agent System — specialized agents communicate via in-proc bus.
    # Does not rewrite FastIntent / TaskPlan / Computer Use; claims multi-specialist goals only.
    try:
        from neuron.agents import maybe_handle_multi_agent
        ma = maybe_handle_multi_agent(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if ma is not None:
            say, acted, mameta = ma
            meta.update({k: v for k, v in (mameta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (mameta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": (mameta or {}).get("agents") or [],
            }
            tr.user(raw)
            tr.final("multi_agent", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((mameta or {}).get("path") or "multi_agent"),
            )
    except Exception as exc:
        _log(f"multi_agent skipped: {exc}")

    # NEURON OS — central orchestration of desktop OS capabilities (compose-only)
    try:
        from neuron.os import maybe_handle_os
        os_hit = maybe_handle_os(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if os_hit is not None:
            say, acted, osmeta = os_hit
            meta.update({k: v for k, v in (osmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (osmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("neuron_os", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((osmeta or {}).get("path") or "neuron_os"),
            )
    except Exception as exc:
        _log(f"neuron_os skipped: {exc}")

    # GitHub Agent — repo/PR/CI intelligence (before Developer so changelog/CI/commit review win)
    try:
        from neuron.github_agent import maybe_handle_github
        ghh = maybe_handle_github(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if ghh is not None:
            say, acted, gmeta = ghh
            meta.update({k: v for k, v in (gmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (gmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("github_agent", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((gmeta or {}).get("path") or "github_agent"),
            )
    except Exception as exc:
        _log(f"github_agent skipped: {exc}")

    # Project Intelligence — automatic codebase map (before Developer so overview/locate/leaks win)
    try:
        from neuron.project_intelligence import maybe_handle_project_intelligence
        pih = maybe_handle_project_intelligence(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if pih is not None:
            say, acted, pimeta = pih
            meta.update({k: v for k, v in (pimeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (pimeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("project_intelligence", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((pimeta or {}).get("path") or "project_intelligence"),
            )
    except Exception as exc:
        _log(f"project_intelligence skipped: {exc}")

    # Self-Healing — crash/freeze/leak/deadlock/CPU/RAM detect + watchdog recover
    try:
        from neuron.self_healing import maybe_handle_self_healing
        shh = maybe_handle_self_healing(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if shh is not None:
            say, acted, shmeta = shh
            meta.update({k: v for k, v in (shmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (shmeta or {}).get("needs_confirm"),
                "recovered": bool((shmeta or {}).get("result", {}).get("acted")),
                "steps": [],
            }
            tr.user(raw)
            tr.final("self_healing", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((shmeta or {}).get("path") or "self_healing"),
            )
    except Exception as exc:
        _log(f"self_healing skipped: {exc}")

    # Workflow Intelligence — learn reusable workflows from Cursor/GitHub/Blender/Unreal/VS Code/Browser
    try:
        from neuron.workflow_intelligence import maybe_handle_workflow_intelligence
        wih = maybe_handle_workflow_intelligence(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if wih is not None:
            say, acted, wimeta = wih
            meta.update({k: v for k, v in (wimeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (wimeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("workflow_intelligence", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((wimeta or {}).get("path") or "workflow_intelligence"),
            )
    except Exception as exc:
        _log(f"workflow_intelligence skipped: {exc}")

    # Plugin Market — production SDK: install/update/hot-reload/scaffold/permissions
    try:
        from neuron.plugin_market import maybe_handle_plugin_market
        pmh = maybe_handle_plugin_market(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if pmh is not None:
            say, acted, pmmeta = pmh
            meta.update({k: v for k, v in (pmmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (pmmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("plugin_market", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((pmmeta or {}).get("path") or "plugin_market"),
            )
    except Exception as exc:
        _log(f"plugin_market skipped: {exc}")

    # Multi-Device — desktop/laptop/remote/VM/cloud control + sync
    try:
        from neuron.multi_device import maybe_handle_multi_device
        mdh = maybe_handle_multi_device(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if mdh is not None:
            say, acted, mdmeta = mdh
            meta.update({k: v for k, v in (mdmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (mdmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("multi_device", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((mdmeta or {}).get("path") or "multi_device"),
            )
    except Exception as exc:
        _log(f"multi_device skipped: {exc}")

    # Production Readiness — audit, diagnostics, wizard, installer, updater
    try:
        from neuron.production import maybe_handle_production
        prh = maybe_handle_production(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if prh is not None:
            say, acted, prmeta = prh
            meta.update({k: v for k, v in (prmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (prmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("production", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((prmeta or {}).get("path") or "production"),
            )
    except Exception as exc:
        _log(f"production skipped: {exc}")

    # UI Grounding — observe/detect/ground before any UI click
    try:
        from neuron.ui_grounding import maybe_handle_ui_grounding
        ugh = maybe_handle_ui_grounding(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if ugh is not None:
            say, acted, ugmeta = ugh
            meta.update({k: v for k, v in (ugmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (ugmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("ui_grounding", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((ugmeta or {}).get("path") or "ui_grounding"),
            )
    except Exception as exc:
        _log(f"ui_grounding skipped: {exc}")

    # Developer Mode — AI software engineer workflows (compose-only; does not modify cores)
    try:
        from neuron.developer import maybe_handle_developer
        dev = maybe_handle_developer(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if dev is not None:
            say, acted, dmeta = dev
            meta.update({k: v for k, v in (dmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (dmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("developer", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((dmeta or {}).get("path") or "developer"),
            )
    except Exception as exc:
        _log(f"developer mode skipped: {exc}")

    # Blender Agent — bpy expert workflows (compose-only; does not modify cores)
    try:
        from neuron.blender_agent import maybe_handle_blender
        bl = maybe_handle_blender(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if bl is not None:
            say, acted, bmeta = bl
            meta.update({k: v for k, v in (bmeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (bmeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("blender_agent", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((bmeta or {}).get("path") or "blender_agent"),
            )
    except Exception as exc:
        _log(f"blender_agent skipped: {exc}")

    # Unreal Agent — UE5 expert workflows (compose-only; does not modify cores)
    try:
        from neuron.unreal_agent import maybe_handle_unreal
        ue = maybe_handle_unreal(
            raw,
            normalized=resolved_request,
            loop=loop,
            confirmed=confirmed,
        )
        if ue is not None:
            say, acted, umeta = ue
            meta.update({k: v for k, v in (umeta or {}).items() if k not in ("loop",)})
            loop_meta = {
                "needs_confirm": (umeta or {}).get("needs_confirm"),
                "recovered": False,
                "steps": [],
            }
            tr.user(raw)
            tr.final("unreal_agent", say or "")
            return _finish(
                say,
                acted,
                meta,
                loop_meta,
                None,
                tr,
                t0,
                path=str((umeta or {}).get("path") or "unreal_agent"),
            )
    except Exception as exc:
        _log(f"unreal_agent skipped: {exc}")

    # V3 CapabilityRouter — high-confidence capabilities.
    # Category A: FastIntentRouter executes tools directly (no AgentLoop).
    # On failure → AgentLoop fallback. Category B / low conf → AgentLoop.
    if cfg.get("capability_router", True):
        try:
            from neuron.v3 import capability_router as cap_mod
            from neuron.brain import fast_router as fast_mod

            routed = cap_mod.route(resolved_request, intent=intent)
            if routed.ok and routed.steps and routed.capability:
                meta["path"] = "capability"
                meta["capability"] = routed.capability.id
                meta["capability_source"] = routed.capability.source
                _log(
                    f"capability id={routed.capability.id} "
                    f"tool={routed.capability.tool} "
                    f"conf={routed.capability.confidence:.2f} "
                    f"src={routed.capability.source}"
                )

                # Prefer fast path (no observe/plan/verify)
                fr = fast_mod.try_handle(
                    resolved_request, intent=intent, confirmed=confirmed
                )
                if (
                    fr is not None
                    and fr.ok
                    and fr.acted
                    and not fr.meta.get("fallback_agent")
                    and not fr.used_agent_loop
                ):
                    meta["path"] = "fast_router"
                    meta["used_agent_loop"] = False
                    meta["fast"] = fr.meta
                    meta["elapsed_ms"] = int((time.time() - t0) * 1000)
                    try:
                        from neuron.perf import current
                        timer = current()
                        if timer is not None:
                            timer.meta["path"] = "fast_router"
                            timer.meta["used_agent_loop"] = False
                            if fr.meta.get("elapsed_ms") is not None:
                                timer.mark("fast_exec_ms", float(fr.meta["elapsed_ms"]))
                    except Exception:
                        pass
                    tr.user(raw)
                    tr.final("fast_router", fr.say or "")
                    meta["trace"] = tr.to_list()
                    _log(
                        f"fast_router capability={routed.capability.id} "
                        f"({meta['elapsed_ms']}ms) no AgentLoop"
                    )
                    try:
                        import memory
                        if fr.say:
                            memory.log("neuron", fr.say)
                    except Exception:
                        pass
                    return fr.say, True, meta

                # Fallback: AgentLoop (preserve full verify/recover)
                _log("fast_router miss/fail → AgentLoop fallback")
                plan_dict = routed.as_plan() or {"say": "", "steps": list(routed.steps)}
                try:
                    for step in plan_dict.get("steps") or []:
                        if (step.get("tool") or "") == "open_app":
                            args = dict(step.get("arguments") or step.get("args") or {})
                            args.setdefault("wait_seconds", 3)
                            if "arguments" in step or "args" not in step:
                                step["arguments"] = args
                            else:
                                step["args"] = args
                except Exception:
                    pass
                plan = normalize_plan(plan_dict)
                t_loop = time.time()
                say, acted, loop_meta, goal = loop.run(
                    request=resolved_request,
                    context="",
                    normalized=intent.normalized or resolved_request,
                    plan=plan,
                    observe_blob=(
                        f"capability={routed.capability.id} "
                        f"tool={routed.capability.tool} "
                        f"fallback=agent_loop"
                    ),
                    confirmed=confirmed,
                )
                meta["used_agent_loop"] = True
                meta["fast_fallback"] = True
                try:
                    from neuron.perf import current
                    timer = current()
                    if timer is not None:
                        timer.mark("act_verify_ms", (time.time() - t_loop) * 1000.0)
                        timer.meta["path"] = "capability_fallback"
                        timer.meta["used_agent_loop"] = True
                except Exception:
                    pass
                return _finish(
                    say, acted, meta, loop_meta, goal, tr, t0, path="capability"
                )
        except Exception as exc:
            _log(f"capability_router skipped: {exc}")

    # Fast path: known recipe / trivial open — try FastRouter first, else AgentLoop
    if intent.kind in ("recipe", "deterministic") and intent.action:
        try:
            from neuron.brain import fast_router as fast_mod
            fr = fast_mod.try_handle(
                resolved_request, intent=intent, confirmed=confirmed
            )
            if fr is not None and fr.ok and fr.acted and not fr.meta.get("fallback_agent"):
                meta["path"] = "fast_router"
                meta["used_agent_loop"] = False
                meta["elapsed_ms"] = int((time.time() - t0) * 1000)
                try:
                    import memory
                    if fr.say:
                        memory.log("neuron", fr.say)
                except Exception:
                    pass
                return fr.say, True, meta
        except Exception:
            pass
        meta["path"] = intent.kind
        plan = normalize_plan({
            "say": "",
            "steps": [{"tool": intent.action, "arguments": intent.args or {}}],
        })
        say, acted, loop_meta, goal = loop.run(
            request=resolved_request,
            context="",
            normalized=intent.normalized or resolved_request,
            plan=plan,
            observe_blob=f"intent={intent.kind} action={intent.action}",
            confirmed=confirmed,
        )
        meta["used_agent_loop"] = True
        return _finish(say, acted, meta, loop_meta, goal, tr, t0, path=intent.kind)

    # LLM planner path (+ Phase 8 context)
    meta["path"] = "llm"

    from neuron.brain import resolver as resolver_mod
    from neuron.brain.snapshot import enrich_snapshot, gather_snapshot

    plan_text = intent.normalized or resolved_request
    snap = gather_snapshot(plan_text, deep=False)
    resolve = resolver_mod.resolve(resolved_request, snap)
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

    plan_request = resolved_request
    plan_normalized = intent.normalized
    if resolve.ambiguous and resolve.band == "high" and resolve.rewritten_request:
        plan_request = resolve.rewritten_request
        plan_normalized = resolve.rewritten_request
        _log(f"resolved -> {plan_request!r} (conf={resolve.confidence:.2f})")

    # AgentLoop: plan inside loop (or rules fallback if planner down)
    say, acted, loop_meta, goal = loop.run(
        request=plan_request,
        context=context,
        normalized=plan_normalized,
        plan=None,
        observe_blob=snap.compact(600),
        confirmed=confirmed,
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
    meta["agent_loop"] = True
    meta["replanned"] = bool(loop_meta.get("replanned"))
    meta["recovered"] = bool(loop_meta.get("recovered"))
    meta["steps"] = loop_meta.get("steps") or []
    meta["diagnoses"] = list(loop_meta.get("diagnoses") or [])
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
        try:
            from neuron.v4.capability.confirm_resume import request_confirm_scoped
            request_confirm_scoped(
                loop_meta["needs_confirm"]["action"],
                loop_meta["needs_confirm"].get("args") or {},
                reason=loop_meta["needs_confirm"].get("reason") or "",
                task=str((meta.get("goal") or {}).get("goal") or ""),
            )
        except Exception:
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
        f"acted={acted} recovered={meta.get('recovered')} "
        f"({meta['elapsed_ms']}ms) say={say!r}"[:240]
    )
    try:
        if acted:
            from neuron.learning_engine import observe_utterance
            req = ""
            try:
                for entry in tr.to_list():
                    if (entry.get("role") or entry.get("kind")) in ("user", "User"):
                        req = str(entry.get("text") or entry.get("content") or "")
                        break
            except Exception:
                pass
            observe_utterance(req or path, acted=True)
    except Exception:
        pass
    try:
        if acted:
            from neuron.memory_engine import observe_utterance as mem_utt
            req2 = ""
            try:
                for entry in tr.to_list():
                    if (entry.get("role") or entry.get("kind")) in ("user", "User"):
                        req2 = str(entry.get("text") or entry.get("content") or "")
                        break
            except Exception:
                pass
            mem_utt(req2 or path, acted=True)
    except Exception:
        pass

    # Personality — modes / emotion / speaking style / humor / conversation memory
    try:
        from neuron.personality import format_reply
        user_txt = ""
        try:
            for entry in tr.to_list():
                role = (entry.get("role") or entry.get("kind") or "").lower()
                if role in ("user",):
                    user_txt = str(entry.get("text") or entry.get("content") or "")
                    if user_txt:
                        break
        except Exception:
            pass
        if say and not str(say).startswith("__"):
            say = format_reply(
                say,
                user=user_txt,
                acted=acted,
                path=path,
                meta=meta,
            )
    except Exception as exc:
        _log(f"personality skipped: {exc}")

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
