"""Register domain skills as planner tools (dotted + underscore names)."""

from __future__ import annotations

from typing import Any, Callable

from neuron.skills import blender, browser, discord, files, spotify, windows, youtube

Handler = Callable[[dict], Any]

# (dotted_name, handler, description, args_schema, risk)
SKILL_SPECS: list[tuple[str, Handler, str, dict, str]] = [
    # YouTube
    ("youtube.search", youtube.search_tool, "Search YouTube (controlled browser)", {"query": "str"}, "safe"),
    ("youtube.play_result", youtube.play_result_tool, "Play Nth visible YouTube video", {"index": "int"}, "safe"),
    ("youtube.home", youtube.home_tool, "Go to YouTube home (do not play)", {}, "safe"),
    ("youtube.play_by_title", youtube.play_by_title_tool, "Play visible YouTube video by title", {"title": "str"}, "safe"),
    ("youtube.list_videos", youtube.list_videos_tool, "List visible YouTube video titles", {}, "safe"),
    ("youtube.skip_ad", youtube.skip_ad_tool, "Skip YouTube ad if present", {}, "safe"),
    ("youtube.fullscreen", youtube.fullscreen_tool, "Toggle YouTube player fullscreen", {"exit": "bool"}, "safe"),
    ("youtube.ensure_playback", youtube.ensure_playback_tool, "Force play/pause on YouTube player", {"want": "str"}, "safe"),
    ("youtube.open_channel_videos", youtube.open_channel_videos_tool, "Open @channel/videos tab", {"channel": "str"}, "safe"),
    ("youtube.play_search", youtube.play_search_tool, "Search YouTube then play Nth result", {"query": "str", "index": "int"}, "safe"),
    # Browser
    ("browser.open_tab", browser.open_tab_tool, "Open/navigate controlled browser tab", {"url": "str"}, "safe"),
    ("browser.navigate", browser.navigate_tool, "Navigate controlled browser to URL", {"url": "str"}, "safe"),
    ("browser.search", browser.search_tool, "Browser search (optional site)", {"query": "str", "site": "str"}, "safe"),
    ("browser.close_tab", browser.close_tab_tool, "Close current browser tab", {}, "safe"),
    ("browser.switch_tab", browser.switch_tab_tool, "Switch browser tab by index", {"index": "int"}, "safe"),
    ("browser.get_tabs", browser.get_tabs_tool, "List browser tabs", {}, "safe"),
    # Windows
    ("windows.focus_app", windows.focus_app_tool, "Focus a desktop app by name", {"name": "str"}, "safe"),
    ("windows.open_app", windows.open_app_tool, "Open/focus a desktop app", {"name": "str"}, "safe"),
    ("windows.close_app", windows.close_app_tool, "Close a desktop app", {"name": "str"}, "confirm"),
    ("windows.move_to_monitor", windows.move_to_monitor_tool, "Move app/window onto a monitor", {"name": "str", "monitor": "str"}, "safe"),
    ("windows.get_monitors", windows.get_monitors_tool, "List connected monitors", {}, "safe"),
    ("windows.maximize", windows.maximize_tool, "Maximize app window", {"name": "str"}, "safe"),
    ("windows.minimize", windows.minimize_tool, "Minimize app window", {"name": "str"}, "safe"),
    # Spotify
    ("spotify.open", spotify.open_tool, "Open/focus Spotify", {}, "safe"),
    ("spotify.play", spotify.play_tool, "Play Spotify (optional search query)", {"query": "str"}, "safe"),
    ("spotify.pause", spotify.pause_tool, "Pause Spotify / media", {}, "safe"),
    ("spotify.next", spotify.next_tool, "Next Spotify track", {}, "safe"),
    ("spotify.previous", spotify.previous_tool, "Previous Spotify track", {}, "safe"),
    ("spotify.search", spotify.search_tool, "Search in Spotify app", {"query": "str"}, "safe"),
    # Discord
    ("discord.open", discord.open_tool, "Open/focus Discord", {}, "safe"),
    ("discord.friends", discord.friends_tool, "Open Discord Friends / DMs", {}, "safe"),
    ("discord.open_channel", discord.open_channel_tool, "Open Discord channel/friends via deep link", {"channel": "str", "guild_id": "str", "channel_id": "str"}, "safe"),
    # Files
    ("files.find", files.find_tool, "Find files under Desktop/Documents/Downloads…", {"query": "str", "root": "str"}, "safe"),
    ("files.open", files.open_tool, "Open a file by path or find+open by query", {"path": "str", "query": "str"}, "safe"),
    ("files.open_folder", files.open_folder_tool, "Open a folder (desktop/downloads/path)", {"location": "str"}, "safe"),
    # Blender
    ("blender.open", blender.open_tool, "Open/focus Blender", {}, "safe"),
    ("blender.focus", blender.focus_tool, "Focus Blender window", {}, "safe"),
    ("blender.open_project", blender.open_project_tool, "Open a .blend project by path or name", {"path": "str", "query": "str"}, "safe"),
    ("blender.new_file", blender.new_file_tool, "New Blender file (Ctrl+N)", {}, "safe"),
]


def underscore_alias(dotted: str) -> str:
    return dotted.replace(".", "_")


def bootstrap_skills(register_fn=None) -> int:
    """Register all skills into the tool registry. Returns count registered."""
    if register_fn is None:
        from neuron.brain import tool_registry
        register_fn = tool_registry.register

    n = 0
    for name, handler, desc, schema, risk in SKILL_SPECS:
        register_fn(
            name,
            handler,
            description=f"skill: {desc}",
            args_schema=schema,
            risk=risk,
            overwrite=True,
        )
        alias = underscore_alias(name)
        if alias != name:
            register_fn(
                alias,
                handler,
                description=f"skill: {desc}",
                args_schema=schema,
                risk=risk,
                overwrite=True,
            )
        n += 1
    return n


def skill_prompt(max_lines: int = 40) -> str:
    """Compact planner hint listing domain skills."""
    lines = [
        "DOMAIN SKILLS (prefer these for repeated workflows):",
        "youtube.search{query} | youtube.play_result{index} | youtube.play_search{query,index?}",
        "youtube.home{} | youtube.fullscreen{exit?} | youtube.skip_ad{} | youtube.open_channel_videos{channel}",
        "browser.open_tab{url} | browser.navigate{url} | browser.search{query,site?}",
        "windows.focus_app{name} | windows.move_to_monitor{name,monitor} | windows.open_app{name}",
        "spotify.play{query?} | spotify.pause{} | spotify.search{query}",
        "discord.open_channel{channel|guild_id,channel_id} | discord.friends{}",
        "files.find{query} | files.open{path|query} | files.open_folder{location}",
        "blender.open_project{path|query} | blender.open{}",
    ]
    return "\n".join(lines[:max_lines])
