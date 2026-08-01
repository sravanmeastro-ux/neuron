"""Centralized tool preference for V4.4 hierarchical planning.

Preferred hierarchy (first available wins):
  domain skill → OS/app tool → UIA → browser → keyboard → semantic UI → coords
"""

from __future__ import annotations

from typing import Any

# Intent → ordered candidate tool names (aliases resolved via ToolRegistry).
_INTENT_CANDIDATES: dict[str, list[str]] = {
    "open_app": ["windows.open_app", "open_app"],
    "focus_app": ["windows.focus_app", "focus_app"],
    "move_monitor": ["windows.move_to_monitor", "move_window_to_monitor", "move_window"],
    "close_app": ["windows.close_app", "close_app"],
    "youtube_search": ["youtube.search", "browser_search", "search_site"],
    "youtube_play": ["youtube.play_result", "play_result"],
    "youtube_fullscreen": ["youtube.fullscreen"],
    "youtube_home": ["youtube.home", "youtube_home", "open_website"],
    "open_website": ["open_website", "browser_navigate"],
    "browser_search": ["browser_search", "search_site"],
    "volume": ["volume"],
    "mute": ["volume"],  # args set_mute / mute
    "media": ["media"],
    "click": ["click_ui_element", "click_element", "browser_click", "click"],
    "type": ["type_text", "browser_type"],
    "press": ["press_keys", "hotkey"],
    "observe": ["analyze_screen", "inspect_screen"],
    "find_file": ["search_files", "find_file"],
    "open_file": ["open_file", "files.open"],
    "spotify_open": ["spotify.open", "open_app"],
    "discord_open": ["discord.open", "open_app"],
}

# Control-method preference rank (lower = better). Used when ranking among equals.
_METHOD_RANK = {
    "skill": 0,
    "api": 1,
    "dom": 2,
    "filesystem": 3,
    "uia": 4,
    "perception": 5,
    "input": 6,
    "coords": 9,
}


def candidates_for_intent(intent: str) -> list[str]:
    return list(_INTENT_CANDIDATES.get((intent or "").strip().lower(), []))


def pick_tool(
    intent: str,
    *,
    preferred: list[str] | None = None,
    require_registered: bool = True,
) -> str | None:
    """Pick first available tool for an intent. Never invents unregistered tools.

    V4.8: prefer CapabilityCatalog.resolve_intent when catalog is already built
    (avoids import cycles during catalog bootstrap).
    """
    try:
        from neuron.v4.capability.catalog import _CATALOG
        if _CATALOG is not None and getattr(_CATALOG, "_built", False) and not getattr(_CATALOG, "_building", False):
            from neuron.v4.capability.resolve import resolve_intent
            res = resolve_intent(intent, preferred=preferred)
            if res.ok and res.tool:
                return res.tool
    except Exception:
        pass

    ordered: list[str] = []
    for name in list(preferred or []) + candidates_for_intent(intent):
        if name and name not in ordered:
            ordered.append(name)
    if not ordered and preferred:
        ordered = list(preferred)

    if not require_registered:
        return ordered[0] if ordered else None

    try:
        from neuron.brain import tool_registry as tr
        tr.ensure_bootstrapped()
    except Exception:
        return ordered[0] if ordered else None

    scored: list[tuple[int, str]] = []
    for name in ordered:
        if not tr.is_registered(name):
            continue
        spec = tr.get(name)
        methods = list(getattr(spec, "control_methods", None) or [])
        rank = 5
        if "." in name:  # domain skill style
            rank = 0
        for m in methods:
            rank = min(rank, _METHOD_RANK.get(str(m).lower(), 5))
        # Prefer planner_visible
        if spec and not getattr(spec, "planner_visible", True):
            rank += 20
        scored.append((rank, tr.resolve_name(name)))

    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]))
    return scored[0][1]


def tool_risk(tool: str) -> str:
    try:
        from neuron.safety.policy import risk_of
        return risk_of(tool) or "safe"
    except Exception:
        try:
            from neuron.brain import tool_registry as tr
            spec = tr.get(tool)
            return (spec.risk if spec else "safe") or "safe"
        except Exception:
            return "safe"


def validate_tool_call(tool: str, args: dict[str, Any] | None) -> tuple[bool, str, dict[str, Any]]:
    try:
        from neuron.brain import tool_registry as tr
        return tr.validate_args(tool, args or {})
    except Exception as exc:
        return False, str(exc), {}


def is_known_tool(name: str) -> bool:
    if not name or name in ("resolve", "observe", "clarify", "skip", "wait"):
        return name in ("resolve", "observe", "clarify", "skip", "wait")
    try:
        from neuron.brain import tool_registry as tr
        return tr.is_registered(name)
    except Exception:
        return False


__all__ = [
    "candidates_for_intent",
    "pick_tool",
    "tool_risk",
    "validate_tool_call",
    "is_known_tool",
]
