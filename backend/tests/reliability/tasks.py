"""Reliability benchmark task catalog (V3.9: 150+ desktop workflows).

Prefer a tight set of high-reliability workflows over thousands of fragile commands.
Each task has: id, request, optional fixed plan, expect_actions, category, tags.
"""

from __future__ import annotations

from typing import Any


def _step(action: str, args: dict | None = None, **extra) -> dict:
    s = {"action": action, "args": args or {}}
    s.update(extra)
    return s


def _task(
    tid: str,
    name: str,
    request: str,
    *,
    category: str,
    expect_actions: list[str],
    plan: list[dict] | None = None,
    tags: list[str] | None = None,
    live: bool = True,
    confirm: bool = True,
) -> dict[str, Any]:
    return {
        "id": tid,
        "name": name,
        "request": request,
        "category": category,
        "expect_actions": expect_actions,
        "plan": plan,
        "tags": tags or [],
        "live": live,
        "confirm": confirm,
    }


def build_tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    # ----- Apps: open / focus / close ---------------------------------
    apps = [
        ("chrome", "Chrome"),
        ("notepad", "Notepad"),
        ("calculator", "Calculator"),
        ("discord", "Discord"),
        ("spotify", "Spotify"),
        ("explorer", "File Explorer"),
        ("edge", "Edge"),
        ("steam", "Steam"),
    ]
    for slug, label in apps:
        tasks.append(_task(
            f"open_{slug}",
            f"Open {label}",
            f"open {slug}",
            category="apps",
            expect_actions=["open_app", "windows.open_app"],
            plan=[_step("open_app", {"name": slug}, expected_result=f"{label} is open")],
            tags=["open", "core"],
        ))
        tasks.append(_task(
            f"focus_{slug}",
            f"Focus {label}",
            f"focus {slug}",
            category="apps",
            expect_actions=["focus_app", "windows.focus_app", "open_app"],
            plan=[_step("focus_app", {"name": slug}, expected_result=f"{label} is focused")],
            tags=["focus"],
        ))

    tasks.append(_task(
        "close_notepad",
        "Close Notepad",
        "close notepad",
        category="apps",
        expect_actions=["close_app", "windows.close_app"],
        plan=[_step("close_app", {"name": "notepad"}, expected_result="Notepad closed")],
        tags=["close"],
        confirm=True,
    ))

    # ----- YouTube / browser ------------------------------------------
    tasks += [
        _task(
            "youtube_home",
            "Go to YouTube home",
            "go to youtube home",
            category="youtube",
            expect_actions=["youtube_home", "youtube.home", "open_website"],
            plan=[_step("youtube_home", {}, expected_result="YouTube home is open")],
            tags=["youtube", "core"],
        ),
        _task(
            "youtube_search",
            "Search YouTube",
            "search youtube for blender tutorials",
            category="youtube",
            expect_actions=["search_site", "youtube.search", "youtube_search"],
            plan=[_step(
                "search_site",
                {"site": "youtube", "query": "blender tutorials"},
                expected_result="YouTube search results visible",
            )],
            tags=["youtube", "search", "core"],
        ),
        _task(
            "youtube_play_first",
            "Play first video",
            "play the first video",
            category="youtube",
            expect_actions=["play_result", "youtube.play_result", "youtube_home_play"],
            plan=[_step("play_result", {"index": 1}, expected_result="watch page playing")],
            tags=["youtube", "play", "core"],
        ),
        _task(
            "youtube_play_second",
            "Play second video",
            "play the second video",
            category="youtube",
            expect_actions=["play_result", "youtube.play_result", "youtube_home_play"],
            plan=[_step("play_result", {"index": 2}, expected_result="second video playing")],
            tags=["youtube", "play", "core"],
        ),
        _task(
            "youtube_play_home_first",
            "Play first on YouTube home",
            "play the first video on the youtube homepage",
            category="youtube",
            expect_actions=["youtube_home_play", "play_result"],
            plan=[_step("youtube_home_play", {"index": 1}, expected_result="first home video playing")],
            tags=["youtube", "play"],
        ),
        _task(
            "youtube_skip_ad",
            "Skip YouTube ad",
            "skip the ad",
            category="youtube",
            expect_actions=["skip_ad", "youtube.skip_ad"],
            plan=[_step("skip_ad", {}, expected_result="ad skipped or no ad")],
            tags=["youtube"],
        ),
        _task(
            "youtube_fullscreen",
            "Fullscreen YouTube",
            "make the video fullscreen",
            category="youtube",
            expect_actions=["fullscreen", "youtube.fullscreen"],
            plan=[_step("fullscreen", {}, expected_result="video is fullscreen")],
            tags=["youtube"],
        ),
        _task(
            "youtube_pause",
            "Pause video",
            "pause the video",
            category="youtube",
            expect_actions=["ensure_playback", "youtube.ensure_playback"],
            plan=[_step("ensure_playback", {"want": "pause"}, expected_result="video paused")],
            tags=["youtube"],
        ),
        _task(
            "youtube_play_resume",
            "Resume video",
            "play the video",
            category="youtube",
            expect_actions=["ensure_playback", "youtube.ensure_playback", "play_result"],
            plan=[_step("ensure_playback", {"want": "play"}, expected_result="video playing")],
            tags=["youtube"],
        ),
        _task(
            "browser_open_google",
            "Open Google",
            "open google.com",
            category="browser",
            expect_actions=["open_website", "browser.open_tab", "browser_open"],
            plan=[_step("open_website", {"site": "google.com"}, expected_result="Google is open")],
            tags=["browser"],
        ),
        _task(
            "browser_search_web",
            "Search the web",
            "search the web for weather in delhi",
            category="browser",
            expect_actions=["search_web", "search_site", "browser.search"],
            plan=[_step("search_web", {"query": "weather in delhi"}, expected_result="search results")],
            tags=["browser", "search"],
        ),
        _task(
            "browser_scroll_down",
            "Scroll page down",
            "scroll down on the page",
            category="browser",
            expect_actions=["page_scroll", "browser_scroll", "scroll"],
            plan=[_step("page_scroll", {"direction": "down"}, expected_result="page scrolled")],
            tags=["scroll"],
        ),
        _task(
            "browser_scroll_up",
            "Scroll page up",
            "scroll up",
            category="browser",
            expect_actions=["page_scroll", "browser_scroll", "scroll"],
            plan=[_step("page_scroll", {"direction": "up"}, expected_result="page scrolled up")],
            tags=["scroll"],
        ),
    ]

    # ----- Window / monitor -------------------------------------------
    tasks += [
        _task(
            "switch_to_discord",
            "Switch to Discord",
            "switch to discord",
            category="windows",
            expect_actions=["focus_app", "windows.focus_app", "open_app"],
            plan=[_step("focus_app", {"name": "discord"}, expected_result="Discord focused")],
            tags=["focus", "core"],
        ),
        _task(
            "return_to_chrome",
            "Return to Chrome",
            "go back to chrome",
            category="windows",
            expect_actions=["focus_app", "windows.focus_app", "open_app"],
            plan=[_step("focus_app", {"name": "chrome"}, expected_result="Chrome focused")],
            tags=["focus", "core"],
        ),
        _task(
            "move_chrome_monitor_2",
            "Move Chrome to screen 2",
            "move chrome to monitor 2",
            category="windows",
            expect_actions=["move_window_to_monitor", "windows.move_to_monitor", "move_window"],
            plan=[_step(
                "move_window_to_monitor",
                {"title": "Chrome", "monitor": 2},
                expected_result="Chrome on monitor 2",
            )],
            tags=["monitor", "core"],
        ),
        _task(
            "move_chrome_monitor_1",
            "Move Chrome to screen 1",
            "move chrome to monitor 1",
            category="windows",
            expect_actions=["move_window_to_monitor", "windows.move_to_monitor", "move_window"],
            plan=[_step(
                "move_window_to_monitor",
                {"title": "Chrome", "monitor": 1},
                expected_result="Chrome on monitor 1",
            )],
            tags=["monitor"],
        ),
        _task(
            "list_monitors",
            "List monitors",
            "what monitors do I have",
            category="windows",
            expect_actions=["get_monitors", "windows.get_monitors"],
            plan=[_step("get_monitors", {}, expected_result="monitor list")],
            tags=["monitor"],
        ),
        _task(
            "maximize_chrome",
            "Maximize Chrome",
            "maximize chrome",
            category="windows",
            expect_actions=["maximize_app", "windows.maximize", "window"],
            plan=[_step("maximize_app", {"name": "chrome"}, expected_result="Chrome maximized")],
            tags=["window"],
        ),
        _task(
            "minimize_notepad",
            "Minimize Notepad",
            "minimize notepad",
            category="windows",
            expect_actions=["minimize_app", "windows.minimize", "window"],
            plan=[_step("minimize_app", {"name": "notepad"}, expected_result="Notepad minimized")],
            tags=["window"],
        ),
        _task(
            "get_active_window",
            "Get active window",
            "what window is focused",
            category="windows",
            expect_actions=["get_active_window"],
            plan=[_step("get_active_window", {}, expected_result="active window reported")],
            tags=["perceive"],
        ),
        _task(
            "list_windows",
            "List windows",
            "list open windows",
            category="windows",
            expect_actions=["get_windows"],
            plan=[_step("get_windows", {}, expected_result="window list")],
            tags=["perceive"],
        ),
    ]

    # ----- Files ------------------------------------------------------
    tasks += [
        _task(
            "open_downloads",
            "Open Downloads",
            "open downloads",
            category="files",
            expect_actions=["open_folder", "files.open_folder"],
            plan=[_step("open_folder", {"location": "downloads"}, expected_result="Downloads open")],
            tags=["files", "core"],
        ),
        _task(
            "open_documents",
            "Open Documents",
            "open documents folder",
            category="files",
            expect_actions=["open_folder", "files.open_folder"],
            plan=[_step("open_folder", {"location": "documents"}, expected_result="Documents open")],
            tags=["files"],
        ),
        _task(
            "open_desktop_folder",
            "Open Desktop folder",
            "open desktop folder",
            category="files",
            expect_actions=["open_folder", "files.open_folder"],
            plan=[_step("open_folder", {"location": "desktop"}, expected_result="Desktop folder open")],
            tags=["files"],
        ),
        _task(
            "find_pdf",
            "Find a PDF file",
            "find a pdf file",
            category="files",
            expect_actions=["search_files", "files.find"],
            plan=[_step("search_files", {"query": "*.pdf"}, expected_result="pdf matches listed")],
            tags=["files", "core"],
        ),
        _task(
            "find_blend",
            "Find a Blender file",
            "find a blend file",
            category="files",
            expect_actions=["search_files", "files.find"],
            plan=[_step("search_files", {"query": "*.blend"}, expected_result="blend matches listed")],
            tags=["files"],
        ),
        _task(
            "search_files_report",
            "Find particular file by name",
            "find report.pdf",
            category="files",
            expect_actions=["search_files", "files.find", "files.open"],
            plan=[_step("search_files", {"query": "report.pdf"}, expected_result="search ran")],
            tags=["files", "core"],
        ),
    ]

    # ----- Input: type / copy / paste / keys --------------------------
    tasks += [
        _task(
            "open_notepad_type",
            "Open Notepad and type text",
            "open notepad and type hello from neuron",
            category="input",
            expect_actions=["open_app", "type_text"],
            plan=[
                _step("open_app", {"name": "notepad"}, expected_result="Notepad open"),
                _step("type_text", {"text": "hello from neuron"}, expected_result="text typed"),
            ],
            tags=["type", "core"],
            confirm=True,
        ),
        _task(
            "type_hello",
            "Type text",
            "type hello world",
            category="input",
            expect_actions=["type_text"],
            plan=[_step("type_text", {"text": "hello world"}, expected_result="typed")],
            tags=["type", "core"],
            confirm=True,
        ),
        _task(
            "copy_selection",
            "Copy selection",
            "copy that",
            category="input",
            expect_actions=["press_keys", "hotkey"],
            plan=[_step("press_keys", {"keys": "control c"}, expected_result="copied")],
            tags=["clipboard", "core"],
        ),
        _task(
            "paste_clipboard",
            "Paste",
            "paste",
            category="input",
            expect_actions=["press_keys", "hotkey"],
            plan=[_step("press_keys", {"keys": "control v"}, expected_result="pasted")],
            tags=["clipboard", "core"],
        ),
        _task(
            "select_all",
            "Select all",
            "select all",
            category="input",
            expect_actions=["press_keys", "hotkey"],
            plan=[_step("press_keys", {"keys": "control a"}, expected_result="selected all")],
            tags=["clipboard"],
        ),
        _task(
            "undo",
            "Undo",
            "undo",
            category="input",
            expect_actions=["press_keys", "hotkey"],
            plan=[_step("press_keys", {"keys": "control z"}, expected_result="undone")],
            tags=["keys"],
        ),
        _task(
            "press_enter",
            "Press Enter",
            "press enter",
            category="input",
            expect_actions=["press_keys", "press_key"],
            plan=[_step("press_keys", {"keys": "enter"}, expected_result="enter pressed")],
            tags=["keys"],
        ),
        _task(
            "press_escape",
            "Press Escape (dismiss popup)",
            "press escape",
            category="recovery",
            expect_actions=["press_keys", "press_key"],
            plan=[_step("press_keys", {"keys": "escape"}, expected_result="escape pressed")],
            tags=["popup", "core"],
        ),
    ]

    # ----- Calculator -------------------------------------------------
    tasks += [
        _task(
            "open_calculator",
            "Open Calculator",
            "open calculator",
            category="apps",
            expect_actions=["open_app"],
            plan=[_step("open_app", {"name": "calculator"}, expected_result="Calculator open")],
            tags=["core"],
        ),
    ]

    # ----- UI element / scroll to target ------------------------------
    tasks += [
        _task(
            "click_search",
            "Click Search UI element",
            "click Search",
            category="ui",
            expect_actions=["click_element", "click_ui_element", "click_text", "find_element"],
            plan=[_step("click_element", {"name": "Search"}, expected_result="Search clicked")],
            tags=["ui", "core"],
        ),
        _task(
            "find_settings_button",
            "Find Settings element",
            "find the Settings button",
            category="ui",
            expect_actions=["find_element", "find_ui_element", "click_element"],
            plan=[_step("find_element", {"name": "Settings"}, expected_result="Settings located")],
            tags=["ui"],
        ),
        _task(
            "scroll_to_element",
            "Scroll toward UI content",
            "scroll down to find more results",
            category="ui",
            expect_actions=["page_scroll", "scroll", "browser_scroll"],
            plan=[_step("page_scroll", {"direction": "down", "amount": 900}, expected_result="scrolled")],
            tags=["scroll", "core"],
        ),
        _task(
            "get_ui_tree",
            "Read UI tree",
            "read the ui tree",
            category="ui",
            expect_actions=["get_ui_tree", "get_active_window_elements"],
            plan=[_step("get_ui_tree", {}, expected_result="ui labels available")],
            tags=["perceive"],
        ),
    ]

    # ----- Recovery scenarios -----------------------------------------
    tasks += [
        _task(
            "recover_popup_escape",
            "Recover from a popup",
            "dismiss the popup",
            category="recovery",
            expect_actions=["press_keys", "click_element", "click_text", "computer_use"],
            plan=[
                _step("press_keys", {"keys": "escape"}, expected_result="popup dismissed"),
            ],
            tags=["popup", "recovery", "core"],
        ),
        _task(
            "recover_wrong_focus",
            "Recover when wrong window focused",
            "chrome is not focused, focus chrome",
            category="recovery",
            expect_actions=["focus_app", "open_app", "windows.focus_app"],
            plan=[
                _step("focus_app", {"name": "chrome"}, expected_result="Chrome focused"),
            ],
            tags=["focus", "recovery", "core"],
        ),
        _task(
            "recover_reopen_chrome",
            "Recover by reopening Chrome",
            "chrome closed somehow, open chrome again",
            category="recovery",
            expect_actions=["open_app"],
            plan=[_step("open_app", {"name": "chrome"}, expected_result="Chrome open")],
            tags=["recovery"],
        ),
        _task(
            "recover_youtube_home",
            "Recover to YouTube home",
            "get back to youtube home",
            category="recovery",
            expect_actions=["youtube_home", "youtube.home", "open_website"],
            plan=[_step("youtube_home", {}, expected_result="YouTube home")],
            tags=["recovery", "youtube"],
        ),
    ]

    # ----- Media / volume ---------------------------------------------
    tasks += [
        _task(
            "volume_up",
            "Volume up",
            "volume up",
            category="media",
            expect_actions=["volume"],
            plan=[_step("volume", {"action": "up"}, expected_result="volume raised")],
            tags=["media"],
        ),
        _task(
            "volume_mute",
            "Mute volume",
            "mute",
            category="media",
            expect_actions=["volume", "player_key"],
            plan=[_step("volume", {"action": "mute"}, expected_result="muted")],
            tags=["media"],
        ),
        _task(
            "media_next",
            "Next track",
            "next song",
            category="media",
            expect_actions=["media", "spotify.next", "player_key"],
            plan=[_step("media", {"action": "next"}, expected_result="next track")],
            tags=["media"],
        ),
        _task(
            "spotify_play",
            "Play Spotify",
            "play spotify",
            category="media",
            expect_actions=["spotify.play", "spotify_play", "open_app", "media"],
            plan=[_step("spotify.play", {}, expected_result="Spotify playing")],
            tags=["spotify"],
        ),
    ]

    # ----- Discord / Steam / Blender skills ---------------------------
    tasks += [
        _task(
            "discord_friends",
            "Open Discord friends",
            "open discord friends",
            category="apps",
            expect_actions=["discord_friends", "discord.friends", "discord.open_channel", "open_app"],
            plan=[_step("discord_friends", {}, expected_result="Discord friends open")],
            tags=["discord"],
        ),
        _task(
            "steam_library",
            "Open Steam library",
            "open steam library",
            category="apps",
            expect_actions=["steam_goto", "open_app"],
            plan=[_step("steam_goto", {"section": "library"}, expected_result="Steam library")],
            tags=["steam"],
        ),
        _task(
            "blender_open",
            "Open Blender",
            "open blender",
            category="apps",
            expect_actions=["open_app", "blender.open"],
            plan=[_step("open_app", {"name": "blender"}, expected_result="Blender open")],
            tags=["blender"],
        ),
        _task(
            "blender_new_project",
            "Create Blender project (procedure)",
            "create a blender project",
            category="procedures",
            expect_actions=["run_procedure", "blender.new_project", "open_app"],
            plan=[_step("run_procedure", {"id": "blender.new_project"}, expected_result="procedure finished")],
            tags=["blender", "procedure", "core"],
        ),
    ]

    # ----- Perception -------------------------------------------------
    tasks += [
        _task(
            "screenshot",
            "Take a screenshot",
            "take a screenshot",
            category="perceive",
            expect_actions=["screenshot", "capture_screen"],
            plan=[_step("screenshot", {}, expected_result="screenshot saved")],
            tags=["perceive"],
        ),
        _task(
            "describe_screen",
            "Describe the screen",
            "what's on my screen",
            category="perceive",
            expect_actions=["describe_screen", "analyze_screen", "get_screen_context", "answer_screen"],
            plan=[_step("describe_screen", {"request": "overview"}, expected_result="description")],
            tags=["perceive"],
        ),
        _task(
            "system_report",
            "System report",
            "system report",
            category="perceive",
            expect_actions=["system_report"],
            plan=[_step("system_report", {}, expected_result="stats reported")],
            tags=["perceive"],
        ),
        _task(
            "list_running_apps",
            "List running apps",
            "what apps are running",
            category="perceive",
            expect_actions=["get_running_apps"],
            plan=[_step("get_running_apps", {}, expected_result="app list")],
            tags=["perceive"],
        ),
    ]

    # ----- Settings / OS ----------------------------------------------
    tasks += [
        _task(
            "open_settings",
            "Open Windows Settings",
            "open windows settings",
            category="os",
            expect_actions=["open_settings"],
            plan=[_step("open_settings", {"page": "home"}, expected_result="Settings open")],
            tags=["os"],
        ),
        _task(
            "bluetooth_settings",
            "Open Bluetooth settings",
            "open bluetooth settings",
            category="os",
            expect_actions=["open_settings"],
            plan=[_step("open_settings", {"page": "bluetooth"}, expected_result="Bluetooth settings")],
            tags=["os"],
        ),
        _task(
            "show_desktop",
            "Show desktop",
            "show desktop",
            category="os",
            expect_actions=["window", "press_keys", "hotkey"],
            plan=[_step("press_keys", {"keys": "win d"}, expected_result="desktop shown")],
            tags=["os"],
        ),
    ]

    # ----- Safety / interrupt (non-destructive checks) ----------------
    tasks += [
        _task(
            "safety_status",
            "Safety status",
            "safety status",
            category="safety",
            expect_actions=[],  # handled by brain escape hatch
            plan=None,
            tags=["safety"],
            live=False,  # voice/brain path, not tool plan
        ),
        _task(
            "blocked_shutdown",
            "Refuse shutdown",
            "shutdown the computer",
            category="safety",
            expect_actions=[],
            plan=None,
            tags=["safety", "blocked"],
            live=False,
        ),
    ]

    # ----- Compound workflows (multi-step) ----------------------------
    tasks += [
        _task(
            "wf_chrome_youtube_search",
            "Chrome then YouTube search",
            "open chrome and search youtube for lo-fi",
            category="workflow",
            expect_actions=["open_app", "search_site", "youtube.search", "open_website"],
            plan=[
                _step("open_app", {"name": "chrome"}, expected_result="Chrome open"),
                _step(
                    "search_site",
                    {"site": "youtube", "query": "lo-fi"},
                    expected_result="YouTube results",
                ),
            ],
            tags=["workflow", "core"],
        ),
        _task(
            "wf_discord_then_chrome",
            "Discord then return to Chrome",
            "switch to discord then go back to chrome",
            category="workflow",
            expect_actions=["focus_app", "open_app"],
            plan=[
                _step("focus_app", {"name": "discord"}, expected_result="Discord focused"),
                _step("focus_app", {"name": "chrome"}, expected_result="Chrome focused"),
            ],
            tags=["workflow", "core"],
        ),
        _task(
            "wf_play_first_fullscreen",
            "Play first video fullscreen",
            "play the first video and make it fullscreen",
            category="workflow",
            expect_actions=["play_result", "fullscreen"],
            plan=[
                _step("play_result", {"index": 1}, expected_result="playing"),
                _step("fullscreen", {}, expected_result="fullscreen"),
            ],
            tags=["workflow", "youtube", "core"],
        ),
        _task(
            "wf_notepad_type_copy",
            "Notepad type and copy",
            "open notepad, type hello, then copy all",
            category="workflow",
            expect_actions=["open_app", "type_text", "press_keys"],
            plan=[
                _step("open_app", {"name": "notepad"}, expected_result="Notepad open"),
                _step("type_text", {"text": "hello"}, expected_result="typed"),
                _step("press_keys", {"keys": "control a"}, expected_result="selected"),
                _step("press_keys", {"keys": "control c"}, expected_result="copied"),
            ],
            tags=["workflow", "input", "core"],
            confirm=True,
        ),
        _task(
            "wf_downloads_find",
            "Open Downloads and find pdf",
            "open downloads and find a pdf",
            category="workflow",
            expect_actions=["open_folder", "search_files", "files.find"],
            plan=[
                _step("open_folder", {"location": "downloads"}, expected_result="Downloads open"),
                _step("search_files", {"query": "*.pdf", "root": "downloads"}, expected_result="pdfs listed"),
            ],
            tags=["workflow", "files", "core"],
        ),
        _task(
            "wf_move_then_youtube",
            "Move Chrome to monitor 2 then YouTube",
            "move chrome to monitor 2 and open youtube",
            category="workflow",
            expect_actions=["move_window_to_monitor", "open_website", "youtube_home"],
            plan=[
                _step(
                    "move_window_to_monitor",
                    {"title": "Chrome", "monitor": 2},
                    expected_result="on monitor 2",
                ),
                _step("youtube_home", {}, expected_result="YouTube home"),
            ],
            tags=["workflow", "monitor"],
        ),
    ]

    # ----- Wait / timing ----------------------------------------------
    tasks.append(_task(
        "wait_one_second",
        "Wait one second",
        "wait one second",
        category="util",
        expect_actions=["wait"],
        plan=[_step("wait", {"seconds": 1}, expected_result="waited")],
        tags=["util"],
    ))

    # ----- Extra core desktop workflows (pad toward ~100) -------------
    extras = [
        _task(
            "open_paint",
            "Open Paint",
            "open paint",
            category="apps",
            expect_actions=["open_app", "windows.open_app"],
            plan=[_step("open_app", {"name": "paint"}, expected_result="Paint is open")],
            tags=["open", "core"],
        ),
        _task(
            "focus_paint",
            "Focus Paint",
            "focus paint",
            category="apps",
            expect_actions=["focus_app", "windows.focus_app"],
            plan=[_step("focus_app", {"name": "paint"}, expected_result="Paint focused")],
            tags=["focus"],
        ),
        _task(
            "open_wordpad",
            "Open WordPad",
            "open wordpad",
            category="apps",
            expect_actions=["open_app"],
            plan=[_step("open_app", {"name": "wordpad"}, expected_result="WordPad open")],
            tags=["open"],
        ),
        _task(
            "youtube_search_music",
            "Search YouTube for music",
            "search youtube for chill music",
            category="youtube",
            expect_actions=["search_site", "youtube.search"],
            plan=[_step(
                "search_site",
                {"site": "youtube", "query": "chill music"},
                expected_result="YouTube results",
            )],
            tags=["youtube", "core"],
        ),
        _task(
            "browser_new_tab",
            "Open new browser tab",
            "open a new tab",
            category="browser",
            expect_actions=["press_keys", "browser.new_tab"],
            plan=[_step("press_keys", {"keys": "control t"}, expected_result="new tab")],
            tags=["browser", "input"],
        ),
        _task(
            "browser_close_tab",
            "Close current tab",
            "close this tab",
            category="browser",
            expect_actions=["press_keys", "browser.close_tab"],
            plan=[_step("press_keys", {"keys": "control w"}, expected_result="tab closed")],
            tags=["browser", "input"],
        ),
        _task(
            "browser_refresh",
            "Refresh page",
            "refresh the page",
            category="browser",
            expect_actions=["press_keys", "browser.refresh"],
            plan=[_step("press_keys", {"keys": "f5"}, expected_result="refreshed")],
            tags=["browser"],
        ),
        _task(
            "open_pictures",
            "Open Pictures folder",
            "open pictures",
            category="files",
            expect_actions=["open_folder", "files.open_folder"],
            plan=[_step("open_folder", {"location": "pictures"}, expected_result="Pictures open")],
            tags=["files"],
        ),
        _task(
            "find_png",
            "Find PNG files",
            "find png files in downloads",
            category="files",
            expect_actions=["search_files", "files.find"],
            plan=[_step(
                "search_files",
                {"query": "*.png", "root": "downloads"},
                expected_result="pngs listed",
            )],
            tags=["files", "core"],
        ),
        _task(
            "type_multiline",
            "Type multiline text",
            "type line one then line two",
            category="input",
            expect_actions=["type_text"],
            plan=[
                _step("type_text", {"text": "line one"}, expected_result="typed"),
                _step("press_keys", {"keys": "enter"}, expected_result="newline"),
                _step("type_text", {"text": "line two"}, expected_result="typed"),
            ],
            tags=["input", "core"],
            confirm=True,
        ),
        _task(
            "cut_selection",
            "Cut selection",
            "cut the selection",
            category="input",
            expect_actions=["press_keys"],
            plan=[_step("press_keys", {"keys": "control x"}, expected_result="cut")],
            tags=["input"],
            confirm=True,
        ),
        _task(
            "recover_focus_notepad",
            "Recover focus to Notepad",
            "focus notepad again",
            category="recovery",
            expect_actions=["focus_app", "open_app"],
            plan=[_step("focus_app", {"name": "notepad"}, expected_result="Notepad focused")],
            tags=["recovery", "core"],
        ),
        _task(
            "click_ok_button",
            "Click OK button",
            "click the ok button",
            category="ui",
            expect_actions=["click_element", "find_element"],
            plan=[_step(
                "click_element",
                {"name": "OK", "control_type": "Button"},
                expected_result="OK clicked",
            )],
            tags=["ui", "recovery"],
        ),
        _task(
            "volume_down",
            "Volume down",
            "turn the volume down",
            category="media",
            expect_actions=["volume"],
            plan=[_step("volume", {"direction": "down"}, expected_result="quieter")],
            tags=["media"],
        ),
        _task(
            "wf_chrome_discord_chrome",
            "Chrome to Discord to Chrome",
            "open chrome, switch to discord, return to chrome",
            category="workflow",
            expect_actions=["open_app", "focus_app"],
            plan=[
                _step("open_app", {"name": "chrome"}, expected_result="Chrome open"),
                _step("focus_app", {"name": "discord"}, expected_result="Discord focused"),
                _step("focus_app", {"name": "chrome"}, expected_result="Chrome focused"),
            ],
            tags=["workflow", "core"],
        ),
        _task(
            "wf_calc_then_notepad",
            "Calculator then Notepad",
            "open calculator then open notepad",
            category="workflow",
            expect_actions=["open_app"],
            plan=[
                _step("open_app", {"name": "calculator"}, expected_result="Calculator open"),
                _step("open_app", {"name": "notepad"}, expected_result="Notepad open"),
            ],
            tags=["workflow", "core"],
        ),
    ]
    tasks.extend(extras)

    # V3.9 expansion (multi-monitor, multi-app, context, skills, failures, …)
    try:
        from tests.reliability.tasks_v39 import build_v39_tasks
    except ImportError:
        from reliability.tasks_v39 import build_v39_tasks  # type: ignore
    tasks.extend(build_v39_tasks())

    # Deduplicate by id while keeping order
    seen = set()
    out = []
    for t in tasks:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    return out


TASKS = build_tasks()


def by_id(tid: str) -> dict | None:
    for t in TASKS:
        if t["id"] == tid:
            return t
    return None


def filter_tasks(
    *,
    category: str = "",
    tag: str = "",
    ids: list[str] | None = None,
    live_only: bool = False,
) -> list[dict]:
    rows = list(TASKS)
    if ids:
        want = set(ids)
        rows = [t for t in rows if t["id"] in want]
    if category:
        rows = [t for t in rows if t["category"] == category]
    if tag:
        rows = [t for t in rows if tag in (t.get("tags") or [])]
    if live_only:
        rows = [t for t in rows if t.get("live", True)]
    return rows
