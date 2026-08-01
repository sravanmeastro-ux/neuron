"""Alternate tool selection for recovery — centralized, safety-aware."""

from __future__ import annotations

from typing import Any

from neuron.v4.plan import tools as plan_tools


# Intent / tool → ordered safe alternates (registered names preferred)
_ALTERNATES: dict[str, list[str]] = {
    "open_app": ["windows.open_app", "open_app", "focus_app", "windows.focus_app"],
    "windows.open_app": ["open_app", "windows.focus_app", "focus_app"],
    "focus_app": ["windows.focus_app", "focus_app", "open_app"],
    "windows.focus_app": ["focus_app", "windows.open_app"],
    "move_window_to_monitor": ["windows.move_to_monitor", "move_window_to_monitor", "move_window"],
    "windows.move_to_monitor": ["move_window_to_monitor", "move_window"],
    "click": ["click_ui_element", "browser_click", "click_element", "click"],
    "uia_click": ["click_ui_element", "browser_click", "click_element", "click"],
    "browser_click": ["click_ui_element", "click_element", "click"],
    "click_element": ["click_ui_element", "browser_click", "find_element"],
    "type_text": ["browser_type", "type_text"],
    "uia_type": ["type_text", "browser_type"],
    "youtube.search": ["youtube.search", "browser_search", "search_site"],
    "browser_search": ["youtube.search", "search_site"],
    "youtube.play_result": ["youtube.play_result", "play_result", "browser_click"],
    "youtube.fullscreen": ["youtube.fullscreen"],  # no spam alternates
    "youtube.home": ["youtube.home", "open_website"],
}


def suggest_alternates(
    tool: str,
    args: dict[str, Any] | None = None,
    *,
    tried: set[str] | None = None,
    intent: str = "",
    allow_coords: bool = False,
    max_n: int = 3,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Return safe alternate (tool, args) pairs not in `tried`.
    Rejects BLOCKED tools. CONFIRM/HIGH still returned but caller must route safety.
    Prefers V4.8 CapabilityCatalog when intent is known.
    """
    args = dict(args or {})
    tried = set(tried or set())
    tool_l = (tool or "").strip()

    if intent:
        try:
            from neuron.v4.capability import suggest_recovery_alternates
            catalog_alts = suggest_recovery_alternates(
                intent, args, tried=tried | {tool_l}, allow_coords=allow_coords
            )
            if catalog_alts:
                return catalog_alts[:max_n]
        except Exception:
            pass

    candidates = list(_ALTERNATES.get(tool_l, []))
    if intent:
        from neuron.v4.plan import tools as plan_tools
        picked = plan_tools.candidates_for_intent(intent)
        for c in picked:
            if c not in candidates:
                candidates.append(c)
    # Prefer pick_tool order
    out: list[tuple[str, dict[str, Any]]] = []
    from neuron.v4.plan import tools as plan_tools
    for name in candidates:
        if not name or name == tool_l:
            continue
        if name in tried:
            continue
        if not plan_tools.is_known_tool(name):
            continue
        risk = plan_tools.tool_risk(name)
        if str(risk).lower() in ("blocked", "forbid"):
            continue
        ok, _err, coerced = plan_tools.validate_tool_call(name, args)
        use_args = coerced if ok else dict(args)
        out.append((name, use_args))
        if len(out) >= max_n:
            break

    if allow_coords and "click" not in tried and plan_tools.is_known_tool("click"):
        if args.get("x") is not None and args.get("y") is not None:
            out.append(("click", {"x": args["x"], "y": args["y"]}))

    return out


def focus_recovery_step(app: str) -> dict[str, Any] | None:
    app = (app or "").strip()
    if not app:
        return None
    tool = plan_tools.pick_tool("focus_app", preferred=["windows.focus_app", "focus_app"])
    if not tool:
        return None
    return {"action": tool, "args": {"name": app}, "expected_result": f"{app} focused"}


def wait_ready_step(seconds: float = 1.5) -> dict[str, Any]:
    return {"action": "wait", "args": {"seconds": float(seconds)}, "expected_result": "waited"}


__all__ = ["suggest_alternates", "focus_recovery_step", "wait_ready_step"]
