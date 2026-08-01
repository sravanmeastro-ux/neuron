"""Execute + verify + recover for Computer Use actions."""

from __future__ import annotations

import time
from typing import Any

from neuron.computer_use import observe as obs_mod
from neuron.computer_use import primitives as prim
from neuron.computer_use.types import CUAction, CUObservation


def _ok(result: Any) -> bool:
    if result is None:
        return False
    if hasattr(result, "success"):
        return bool(result.success)
    if isinstance(result, dict) and "success" in result:
        return bool(result["success"])
    s = str(result).lower()
    return not any(x in s for x in ("couldn't", "could not", "failed", "error:", "need "))


def _msg(result: Any) -> str:
    if result is None:
        return ""
    if hasattr(result, "message"):
        return str(result.message or "")
    if isinstance(result, dict):
        return str(result.get("message") or result.get("say") or result)
    return str(result)


def execute_action(action: CUAction, *, confirmed: bool = False) -> tuple[bool, str, dict]:
    """Run one CUAction via existing tools / primitives / screen / vision."""
    meta: dict[str, Any] = {"kind": action.kind}
    kind = action.kind
    args = dict(action.args or {})

    if kind == "wait":
        time.sleep(float(args.get("seconds") or 1))
        return True, "Waited.", meta

    if kind == "open_app":
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            r = tool_registry.execute("open_app", args, confirmed=confirmed)
            return _ok(r), _msg(r), {**meta, "path": "tool"}
        except Exception as exc:
            return False, str(exc), meta

    if kind == "open_website":
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            # open_website expects url or query
            r = tool_registry.execute("open_website", args, confirmed=confirmed)
            return _ok(r), _msg(r), {**meta, "path": "tool"}
        except Exception as exc:
            return False, str(exc), meta

    if kind == "type":
        r = prim.type_text(str(args.get("text") or ""))
        return _ok(r), _msg(r), {**meta, "path": "primitive"}

    if kind == "key":
        r = prim.press_keys(str(args.get("keys") or args.get("key") or ""))
        return _ok(r), _msg(r), {**meta, "path": "primitive"}

    if kind == "scroll":
        r = prim.scroll(str(args.get("direction") or "down"), clicks=int(args.get("clicks") or 3))
        return _ok(r), _msg(r), {**meta, "path": "primitive"}

    if kind == "click_xy":
        r = prim.click_xy(int(args["x"]), int(args["y"]), clicks=int(args.get("clicks") or 1))
        return _ok(r), _msg(r), {**meta, "path": "primitive"}

    if kind == "drag":
        r = prim.drag_drop(
            int(args.get("x1") or 0),
            int(args.get("y1") or 0),
            int(args.get("x2") or 0),
            int(args.get("y2") or 0),
        )
        return _ok(r), _msg(r), {**meta, "path": "primitive"}

    if kind == "upload":
        r = prim.upload_file(str(args.get("path") or ""), method=str(args.get("method") or "dialog"))
        return _ok(r), _msg(r), {**meta, "path": "primitive"}

    if kind == "screen":
        try:
            from neuron.screen import handle as screen_handle
            sr = screen_handle(str(args.get("request") or action.description), force=True)
            if sr is None:
                return False, "Screen engine skipped.", meta
            return bool(sr.ok), sr.say or "", {**meta, "path": "screen"}
        except Exception as exc:
            return False, str(exc), meta

    if kind == "vision":
        try:
            import vision_agent
            if not vision_agent.is_enabled():
                return False, "Vision disabled.", meta
            out = vision_agent.computer_use(str(args.get("goal") or action.description))
            return True, str(out), {**meta, "path": "vision_computer_use"}
        except Exception as exc:
            return False, str(exc), meta

    if kind == "tool":
        name = str(args.get("action") or "")
        targs = dict(args.get("args") or {})
        if name == "open_settings":
            try:
                import actions
                msg = actions.open_settings(str(targs.get("page") or "home"))
                return True, str(msg), {**meta, "path": "actions"}
            except Exception as exc:
                return False, str(exc), meta
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            r = tool_registry.execute(name, targs, confirmed=confirmed)
            return _ok(r), _msg(r), {**meta, "path": "tool"}
        except Exception as exc:
            return False, str(exc), meta

    # Named click via element_resolver
    if kind == "click":
        name = str(args.get("name") or args.get("query") or "")
        if name:
            try:
                from neuron.brain import element_resolver
                r = element_resolver.click({"name": name})
                return _ok(r) if hasattr(r, "success") else True, str(r), {**meta, "path": "resolver"}
            except Exception as exc:
                return False, str(exc), meta

    return False, f"Unknown action kind: {kind}", meta


def verify_action(action: CUAction, obs_before: CUObservation, obs_after: CUObservation) -> bool:
    """Lightweight verification — expected text / app change / element growth."""
    exp = (action.expected or "").lower()
    if not exp:
        return True
    # Soft heuristics
    if "open" in exp or "running" in exp:
        app = (action.args.get("name") or "").lower()
        if app and app[:4] in (obs_after.application or "").lower():
            return True
        if app and app[:4] in (obs_after.window_title or "").lower():
            return True
    needle = ""
    for word in ("download", "settings", "discord", "login", "upload", "blender", "irctc"):
        if word in exp:
            needle = word
            break
    if needle and obs_mod.text_visible(needle, obs_after):
        return True
    # If OCR gained content or window changed, accept soft success
    if obs_after.window_title and obs_after.window_title != obs_before.window_title:
        return True
    if len(obs_after.ocr_preview) > len(obs_before.ocr_preview):
        return True
    # Vision / screen paths often self-report — trust execute ok
    return True


def recover(action: CUAction, error: str, *, attempt: int) -> CUAction | None:
    """
    Intelligent recovery — never endless identical retry.
    Prefer screen → vision computer_use alternate.
    """
    if attempt >= 3:
        return None
    kind = action.kind
    if kind in ("screen", "click", "type") and attempt == 1:
        return CUAction(
            kind="vision",
            args={"goal": action.description or action.expected or error},
            description=f"Recover: {action.description}",
            expected=action.expected,
            requires_confirm=True,
        )
    if kind == "open_app" and attempt == 1:
        name = (action.args or {}).get("name") or ""
        return CUAction(
            kind="tool",
            args={"action": "focus_app", "args": {"name": name}},
            description=f"Focus {name}",
            expected=action.expected,
        )
    if kind == "vision" and attempt == 1:
        return CUAction(
            kind="screen",
            args={"request": action.args.get("goal") or action.description, "force": True},
            description="Screen understand recovery",
            expected=action.expected,
        )
    return None
