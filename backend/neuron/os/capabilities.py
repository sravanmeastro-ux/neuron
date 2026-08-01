"""OS capability registry — maps OS services to existing NEURON cores."""

from __future__ import annotations

from typing import Any, Callable

from neuron.os.types import CAPABILITY_META, CapabilityId, OsResult

Handler = Callable[[dict[str, Any]], OsResult]


_REGISTRY: dict[str, Handler] = {}


def register(capability: str, handler: Handler) -> None:
    _REGISTRY[capability] = handler


def get(capability: str) -> Handler | None:
    return _REGISTRY.get(capability)


def list_capabilities() -> list[dict[str, Any]]:
    out = []
    for cid, meta in CAPABILITY_META.items():
        out.append({
            "id": cid,
            "label": meta.get("label"),
            "composes": meta.get("composes"),
            "registered": cid in _REGISTRY,
        })
    return out


def _tool(name: str, args: dict | None = None, *, confirmed: bool = True) -> Any:
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    return tool_registry.execute(name, args or {}, confirmed=confirmed)


def _wrap(result: Any, *, capability: str, acted: bool = True) -> OsResult:
    ok = True
    msg = str(result)
    if hasattr(result, "ok"):
        ok = bool(result.ok)
        msg = str(getattr(result, "message", None) or getattr(result, "say", None) or msg)
    elif isinstance(result, dict):
        ok = bool(result.get("ok", result.get("success", True)))
        msg = str(result.get("message") or result.get("error") or msg)
    return OsResult(ok=ok, say=msg[:500], acted=acted and ok, capability=capability, data={"raw": str(result)[:300]})


# --- Capability handlers (compose only) ---

def _launcher(args: dict[str, Any]) -> OsResult:
    name = str(args.get("name") or args.get("app") or args.get("query") or "").strip()
    if not name:
        return OsResult(ok=False, error="launcher needs name", capability=CapabilityId.LAUNCHER.value)
    # Prefer plugin open if present
    plug = f"{name.lower().replace(' ', '')}.open"
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        if tool_registry.get(plug) or tool_registry.get(plug.replace(".", "_")):
            t = plug if tool_registry.get(plug) else plug.replace(".", "_")
            return _wrap(_tool(t, {}), capability=CapabilityId.LAUNCHER.value)
    except Exception:
        pass
    return _wrap(_tool("open_app", {"name": name}), capability=CapabilityId.LAUNCHER.value)


def _window_manager(args: dict[str, Any]) -> OsResult:
    op = str(args.get("op") or "list").lower()
    if op in ("list", "windows"):
        return _wrap(_tool("get_windows", {}), capability=CapabilityId.WINDOW_MANAGER.value, acted=False)
    if op in ("active", "foreground"):
        return _wrap(_tool("get_active_window", {}), capability=CapabilityId.WINDOW_MANAGER.value, acted=False)
    if op in ("focus",):
        return _wrap(_tool("focus_app", {"name": args.get("name") or ""}), capability=CapabilityId.WINDOW_MANAGER.value)
    if op in ("minimize",):
        return _wrap(_tool("minimize_app", {"name": args.get("name") or ""}), capability=CapabilityId.WINDOW_MANAGER.value)
    if op in ("maximize",):
        return _wrap(_tool("maximize_app", {"name": args.get("name") or ""}), capability=CapabilityId.WINDOW_MANAGER.value)
    if op in ("move", "monitor"):
        return _wrap(
            _tool("move_window_to_monitor", {
                "title": args.get("title") or "",
                "name": args.get("name") or "",
                "monitor": args.get("monitor") or "other",
            }),
            capability=CapabilityId.WINDOW_MANAGER.value,
        )
    return OsResult(ok=False, error=f"Unknown window op: {op}", capability=CapabilityId.WINDOW_MANAGER.value)


def _system_monitor(args: dict[str, Any]) -> OsResult:
    try:
        from neuron.windows import state as win_state
        snap = win_state.snapshot() if hasattr(win_state, "snapshot") else None
        if snap is None:
            # Fallback tools
            apps = _tool("get_running_apps", {})
            mons = _tool("get_monitors", {})
            return OsResult(
                ok=True,
                say="System snapshot (apps + monitors).",
                acted=False,
                capability=CapabilityId.SYSTEM_MONITOR.value,
                data={"apps": str(apps)[:400], "monitors": str(mons)[:400]},
            )
        return OsResult(
            ok=True,
            say="System snapshot ready.",
            acted=False,
            capability=CapabilityId.SYSTEM_MONITOR.value,
            data=snap if isinstance(snap, dict) else {"snapshot": str(snap)[:800]},
        )
    except Exception as exc:
        return OsResult(ok=False, error=str(exc), capability=CapabilityId.SYSTEM_MONITOR.value)


def _notifications(args: dict[str, Any]) -> OsResult:
    msg = str(args.get("message") or args.get("text") or "").strip()
    level = str(args.get("level") or "info")
    if not msg:
        # Open Windows notification settings as hub entry
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            if tool_registry.get("open_settings"):
                return _wrap(_tool("open_settings", {"page": "notifications"}), capability=CapabilityId.NOTIFICATIONS.value)
        except Exception:
            pass
        return OsResult(ok=True, say="Notification manager ready. Pass message to notify.", capability=CapabilityId.NOTIFICATIONS.value)
    # Voice-first notification via TTS when available
    try:
        from neuron.speech.tts import speak
        speak(msg)
    except Exception:
        pass
    return OsResult(
        ok=True,
        say=f"[{level}] {msg}",
        acted=True,
        capability=CapabilityId.NOTIFICATIONS.value,
        data={"level": level, "message": msg},
    )


def _automation_hub(args: dict[str, Any]) -> OsResult:
    op = str(args.get("op") or "list").lower()
    if op in ("list", "workflows"):
        return _wrap(_tool("workflow_list", {}), capability=CapabilityId.AUTOMATION_HUB.value, acted=False)
    if op in ("run", "workflow"):
        return _wrap(
            _tool("workflow_run", {"id": args.get("id") or args.get("name") or "", "dry_run": args.get("dry_run", False)}),
            capability=CapabilityId.AUTOMATION_HUB.value,
        )
    if op in ("record",):
        return _wrap(
            _tool("workflow_record", {"action": args.get("action") or "start", "name": args.get("name") or ""}),
            capability=CapabilityId.AUTOMATION_HUB.value,
        )
    if op in ("plan", "task"):
        return _wrap(
            _tool("run_task_workflow", {"request": args.get("text") or args.get("goal") or "", "confirmed": bool(args.get("confirmed"))}),
            capability=CapabilityId.AUTOMATION_HUB.value,
        )
    return OsResult(ok=False, error=f"Unknown automation op: {op}", capability=CapabilityId.AUTOMATION_HUB.value)


def _voice_first(args: dict[str, Any]) -> OsResult:
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8"))
        voice = cfg.get("voice") or {}
        assistant = cfg.get("assistant") or {}
        return OsResult(
            ok=True,
            say="Voice-first desktop active." if voice.get("hands_free") else "Voice configured.",
            acted=False,
            capability=CapabilityId.VOICE_FIRST.value,
            data={
                "hands_free": voice.get("hands_free"),
                "listen_mode": voice.get("listen_mode"),
                "streaming": voice.get("streaming_voice_engine"),
                "personality_mode": assistant.get("mode"),
            },
        )
    except Exception as exc:
        return OsResult(ok=False, error=str(exc), capability=CapabilityId.VOICE_FIRST.value)


def _context(args: dict[str, Any]) -> OsResult:
    text = str(args.get("text") or args.get("query") or "").strip()
    data: dict[str, Any] = {}
    try:
        from neuron.v4.context import understand_for_agent
        u = understand_for_agent(text or "status")
        data["v4"] = u.to_dict() if hasattr(u, "to_dict") else str(u)
    except Exception as exc:
        data["v4_error"] = str(exc)
    try:
        from neuron.personality import buffer
        data["conversation"] = buffer.recent(3)
    except Exception:
        pass
    return OsResult(ok=True, say="Context gathered.", acted=False, capability=CapabilityId.CONTEXT.value, data=data)


def _computer_use(args: dict[str, Any]) -> OsResult:
    text = str(args.get("text") or args.get("goal") or "").strip()
    if not text:
        return OsResult(ok=False, error="computer_use needs goal", capability=CapabilityId.COMPUTER_USE.value)
    try:
        from neuron.computer_use.agent import handle
        out = handle(text, confirmed=bool(args.get("confirmed")), loop=args.get("loop"))
        if out is None:
            return OsResult(ok=False, error="Computer Use declined goal", capability=CapabilityId.COMPUTER_USE.value)
        say, acted, meta = out
        return OsResult(ok=True, say=say or "", acted=acted, capability=CapabilityId.COMPUTER_USE.value, data=meta or {})
    except Exception as exc:
        return OsResult(ok=False, error=str(exc), capability=CapabilityId.COMPUTER_USE.value)


def _ai_planning(args: dict[str, Any]) -> OsResult:
    text = str(args.get("text") or args.get("goal") or "").strip()
    if not text:
        return OsResult(ok=False, error="planning needs goal", capability=CapabilityId.AI_PLANNING.value)
    try:
        from neuron.autonomous.engine import handle_autonomous
        out = handle_autonomous(text, confirmed=bool(args.get("confirmed")), force=True)
        if out is None:
            return OsResult(ok=False, error="Not a plannable workflow", capability=CapabilityId.AI_PLANNING.value)
        say, acted, meta = out
        return OsResult(ok=True, say=say or "", acted=acted, capability=CapabilityId.AI_PLANNING.value, data=meta or {})
    except Exception as exc:
        return OsResult(ok=False, error=str(exc), capability=CapabilityId.AI_PLANNING.value)


def _vision(args: dict[str, Any]) -> OsResult:
    req = str(args.get("request") or args.get("text") or args.get("query") or "describe the screen").strip()
    try:
        from neuron.screen import handle as screen_handle
        sr = screen_handle(req, force=True)
        if sr is not None:
            return OsResult(
                ok=bool(sr.ok),
                say=sr.say or "",
                acted=bool(sr.acted),
                capability=CapabilityId.VISION.value,
            )
    except Exception:
        pass
    return _wrap(_tool("screen_understand", {"request": req}), capability=CapabilityId.VISION.value)


def _memory(args: dict[str, Any]) -> OsResult:
    op = str(args.get("op") or "query").lower()
    text = str(args.get("text") or args.get("query") or "").strip()
    try:
        from neuron import memory_engine as mem
        if op in ("remember", "store") and text:
            item = mem.remember(text)
            return OsResult(ok=True, say="Remembered.", acted=True, capability=CapabilityId.MEMORY.value, data={"id": getattr(item, "item_id", "")})
        if op in ("prompt",):
            blob = mem.for_prompt()
            return OsResult(ok=True, say=blob[:400] or "(empty)", acted=False, capability=CapabilityId.MEMORY.value, data={"prompt": blob[:2000]})
        hits = mem.query_memories(text or "recent")
        return OsResult(ok=True, say=str(hits)[:400], acted=False, capability=CapabilityId.MEMORY.value, data={"hits": hits})
    except Exception as exc:
        return OsResult(ok=False, error=str(exc), capability=CapabilityId.MEMORY.value)


def _learning(args: dict[str, Any]) -> OsResult:
    try:
        from neuron.learning_engine import snapshot, favorites, predict_next
        data: dict[str, Any] = {
            "snapshot": snapshot(),
            "predict": predict_next(limit=5),
        }
        try:
            data["favorites_apps"] = favorites("app", limit=5)
        except Exception:
            data["favorites_apps"] = []
        return OsResult(
            ok=True,
            say="Learning engine status.",
            acted=False,
            capability=CapabilityId.LEARNING.value,
            data=data,
        )
    except Exception as exc:
        return OsResult(ok=False, error=str(exc), capability=CapabilityId.LEARNING.value)


def _plugins(args: dict[str, Any]) -> OsResult:
    return _wrap(_tool("plugins_list", {}), capability=CapabilityId.PLUGINS.value, acted=False)


def bootstrap_capabilities() -> list[str]:
    """Register all OS capability handlers."""
    mapping = {
        CapabilityId.LAUNCHER.value: _launcher,
        CapabilityId.WINDOW_MANAGER.value: _window_manager,
        CapabilityId.SYSTEM_MONITOR.value: _system_monitor,
        CapabilityId.NOTIFICATIONS.value: _notifications,
        CapabilityId.AUTOMATION_HUB.value: _automation_hub,
        CapabilityId.VOICE_FIRST.value: _voice_first,
        CapabilityId.CONTEXT.value: _context,
        CapabilityId.COMPUTER_USE.value: _computer_use,
        CapabilityId.AI_PLANNING.value: _ai_planning,
        CapabilityId.VISION.value: _vision,
        CapabilityId.MEMORY.value: _memory,
        CapabilityId.LEARNING.value: _learning,
        CapabilityId.PLUGINS.value: _plugins,
    }
    for cid, fn in mapping.items():
        register(cid, fn)
    return list(mapping.keys())
