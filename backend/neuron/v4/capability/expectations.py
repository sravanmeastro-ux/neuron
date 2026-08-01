"""Map capabilities → V4.5 verification expectation kinds."""

from __future__ import annotations

# tool/capability patterns → ExpectationKind-ish labels
_VERIFY_MAP: dict[str, str] = {
    "open_app": "APP_OPEN",
    "windows.open_app": "APP_OPEN",
    "focus_app": "WINDOW_FOCUSED",
    "windows.focus_app": "WINDOW_FOCUSED",
    "close_app": "APP_CLOSED",
    "windows.close_app": "APP_CLOSED",
    "move_window_to_monitor": "WINDOW_ON_MONITOR",
    "windows.move_to_monitor": "WINDOW_ON_MONITOR",
    "maximize_app": "WINDOW_STATE",
    "windows.maximize": "WINDOW_STATE",
    "minimize_app": "WINDOW_STATE",
    "windows.minimize": "WINDOW_STATE",
    "open_website": "URL_MATCH",
    "browser_navigate": "URL_MATCH",
    "browser.navigate": "URL_MATCH",
    "browser_open": "URL_MATCH",
    "browser.open_tab": "URL_MATCH",
    "browser_search": "PAGE_STATE",
    "browser.search": "PAGE_STATE",
    "search_site": "PAGE_STATE",
    "youtube.search": "PAGE_STATE",
    "youtube.play_result": "PAGE_STATE",
    "play_result": "PAGE_STATE",
    "youtube.fullscreen": "MEDIA_FULLSCREEN",
    "fullscreen": "MEDIA_FULLSCREEN",
    "youtube.ensure_playback": "MEDIA_PLAYBACK",
    "ensure_playback": "MEDIA_PLAYBACK",
    "media": "MEDIA_PLAYBACK",
    "volume": "SYSTEM_VOLUME",
    "type_text": "TEXT_ENTERED",
    "click_element": "UI_CHANGED",
    "click_ui_element": "UI_CHANGED",
    "browser_click": "UI_CHANGED",
    "click": "UI_CHANGED",
    "open_file": "FILE_OPEN",
    "files.open": "FILE_OPEN",
    "search_files": "FILE_LIST",
    "files.find": "FILE_LIST",
    "wait": "WAITED",
    "speak": "SPOKEN",
}


_PRECONDITIONS: dict[str, list[str]] = {
    "youtube.play_result": ["result_set_or_index"],
    "play_result": ["result_set_or_index"],
    "youtube.fullscreen": ["browser_or_media_context"],
    "fullscreen": ["browser_or_media_context"],
    "move_window_to_monitor": ["target_window_or_app"],
    "windows.move_to_monitor": ["target_window_or_app"],
    "browser_navigate": ["browser_available_or_open"],
    "type_text": ["focus_or_target"],
    "browser_type": ["focus_or_target"],
}


def verification_for(tool: str) -> str:
    t = (tool or "").strip()
    if t in _VERIFY_MAP:
        return _VERIFY_MAP[t]
    # prefix heuristics
    if t.startswith("youtube."):
        if "fullscreen" in t:
            return "MEDIA_FULLSCREEN"
        if "search" in t:
            return "PAGE_STATE"
        return "PAGE_STATE"
    if t.startswith("windows."):
        if "move" in t:
            return "WINDOW_ON_MONITOR"
        if "focus" in t or "open" in t:
            return "WINDOW_FOCUSED" if "focus" in t else "APP_OPEN"
    if t.startswith("browser."):
        return "URL_MATCH" if "nav" in t or "open" in t else "PAGE_STATE"
    if t.startswith("blender."):
        return "APP_STATE"
    if t.startswith("spotify.") or t.startswith("discord."):
        return "APP_STATE"
    return "ACTION_EFFECT"


def preconditions_for(tool: str) -> list[str]:
    return list(_PRECONDITIONS.get((tool or "").strip(), []))


__all__ = ["verification_for", "preconditions_for"]
