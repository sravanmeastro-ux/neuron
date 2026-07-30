"""Tool registry — name → schema, handler, risk level.

Planner never touches the OS; it only emits action names registered here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from neuron.catalog import DEFAULT_RISK, LEGACY_EXECUTORS, NEW_TOOLS

Handler = Callable[[dict], Any]


@dataclass
class ToolSpec:
    name: str
    handler: Handler
    description: str = ""
    args_schema: dict = field(default_factory=dict)
    risk: str = "low"  # low | medium | high | confirm
    verify: str = ""  # optional verify hint for verifier


_REGISTRY: dict[str, ToolSpec] = {}
_BOOTSTRAPPED = False


def register(
    name: str,
    handler: Handler,
    *,
    description: str = "",
    args_schema: dict | None = None,
    risk: str | None = None,
    verify: str = "",
    overwrite: bool = False,
) -> None:
    if name in _REGISTRY and not overwrite:
        return
    _REGISTRY[name] = ToolSpec(
        name=name,
        handler=handler,
        description=description or name,
        args_schema=args_schema or {},
        risk=risk or DEFAULT_RISK.get(name, "medium"),
        verify=verify,
    )


def get(name: str) -> ToolSpec | None:
    ensure_bootstrapped()
    return _REGISTRY.get(name)


def all_tools() -> list[ToolSpec]:
    ensure_bootstrapped()
    return list(_REGISTRY.values())


def names() -> list[str]:
    ensure_bootstrapped()
    return sorted(_REGISTRY.keys())


def tools_doc(limit: int = 80) -> str:
    """Compact card for the LLM planner — single source of truth."""
    ensure_bootstrapped()
    lines = [
        "TOOLS (call with {\"tool\":\"name\",\"arguments\":{...}}):",
        "Prefer structured tools. Coordinate mouse is LAST resort.",
    ]
    for spec in sorted(_REGISTRY.values(), key=lambda s: s.name)[:limit]:
        args = ",".join(f"{k}:{v}" for k, v in (spec.args_schema or {}).items()) if spec.args_schema else ""
        bit = "{" + args + "}" if args else "{}"
        lines.append(f"- {spec.name}{bit} risk={spec.risk} — {spec.description}")
    lines.append(
        "HIERARCHY: direct API/deep-link → UI Automation → browser DOM → OCR → vision → coords."
    )
    lines.append(
        'Examples: browser_search{"site":"youtube","query":"ue5"} → browser_click first result | '
        'browser_research{"query":"RTX 5090 benchmarks"} | click_ui_element{"name":"Settings"} | '
        'open_app{"name":"Blender"}'
    )
    lines.append(
        "Perceive: analyze_screen / get_screen_context (UIA→OCR→local VLM). No cloud vision."
    )
    lines.append(
        "Browser: DOM/a11y first (browser_get_elements/find/click/type). Vision/mouse last."
    )
    lines.append(
        "UI: prefer get_ui_tree → find_ui_element → click_ui_element before mouse coords / computer_use."
    )
    return "\n".join(lines)


def ensure_bootstrapped() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    _bootstrap_legacy()
    _bootstrap_new()


def _bootstrap_legacy() -> None:
    """Wrap brain._EXECUTORS so existing handlers stay authoritative."""
    try:
        import brain as brain_mod
    except Exception:
        return
    executors = getattr(brain_mod, "_EXECUTORS", {}) or {}
    # Richer schemas for common tools
    schemas = {
        "open_app": {"name": "str (or application)"},
        "close_app": {"name": "str"},
        "open_website": {"site": "str"},
        "search_site": {"site": "str", "query": "str"},
        "search_web": {"query": "str"},
        "steam_goto": {"section": "str"},
        "type_text": {"text": "str"},
        "press_keys": {"keys": "str"},
        "play_result": {"index": "int"},
        "youtube_home_play": {"index": "int"},
        "play_by_title": {"title": "str"},
        "computer_use": {"goal": "str"},
        "click_ui_element": {"name": "str"},
        "describe_screen": {"request": "str"},
    }
    descriptions = {
        "open_app": "Launch or focus a desktop application (Blender, Notepad, Discord, Steam…)",
        "open_website": "Open a website in the controlled browser (youtube, google, gmail…)",
        "search_site": "Search on a site (youtube/google) then show results",
        "search_web": "Open a web search for a query",
        "steam_goto": "Open a Steam section (library/store/friends/downloads)",
        "discord_friends": "Open Discord Friends / DMs",
        "youtube_home": "Go to YouTube homepage (do not play)",
        "play_result": "Play the Nth visible YouTube video on screen",
        "computer_use": "Vision+mouse for unknown on-screen UI",
        "click_ui_element": "Click a UI Automation element by accessible name",
        "get_ui_tree": "Read foreground window UI labels",
    }
    for name, fn in executors.items():
        if name in _REGISTRY:
            continue
        # Wrap open_app to accept application alias
        handler = fn
        if name == "open_app":
            def _open(a, _fn=fn):
                a = dict(a or {})
                if not a.get("name"):
                    a["name"] = a.get("application") or a.get("app") or ""
                return _fn(a)
            handler = _open
        register(
            name,
            handler,
            description=descriptions.get(name, f"legacy:{name}"),
            args_schema=schemas.get(name, {}),
            risk=DEFAULT_RISK.get(name, "medium"),
        )


def _bootstrap_new() -> None:
    from neuron.tools import apps as apps_t
    from neuron.tools import windows as win_t
    from neuron.tools import uia_tools
    from neuron.tools import screen_tools
    from neuron.tools import browser_tools
    from neuron.tools import shell_tools
    from neuron.tools import web_tools
    from neuron.tools import input_tools
    from neuron.tools import files_tools

    extras = [
        # Phase 2 Windows control (overwrite legacy thin wrappers)
        ("open_app", apps_t.open_app, "Launch or focus a desktop app (resolves chrome/browser/Blender…)", {"name": "str"}, True),
        ("close_app", apps_t.close_app, "Close a named app/window", {"name": "str"}, True),
        ("focus_app", apps_t.focus_app, "Focus an app by natural name", {"name": "str"}, True),
        ("minimize_app", apps_t.minimize_app, "Minimize app window by name (or foreground)", {"name": "str"}, True),
        ("maximize_app", apps_t.maximize_app, "Maximize app window by name (or foreground)", {"name": "str"}, True),
        ("get_running_apps", apps_t.get_running_apps, "List running app processes + window titles", {}, True),
        ("get_windows", win_t.get_windows, "List top-level windows (includes monitor_id)", {}, True),
        ("get_active_window", win_t.get_active_window, "Get the foreground window title/hwnd + monitor", {}, True),
        ("move_window", win_t.move_window, "Move window to monitor (id/left/right/main/other) or x,y", {"title": "str", "monitor": "str", "x": "int", "y": "int"}, True),
        ("move_window_to_monitor", win_t.move_window_to_monitor, "Move app/window onto a monitor and verify placement", {"title": "str", "monitor": "str", "name": "str"}, True),
        ("resize_window", win_t.resize_window, "Resize window width/height", {"title": "str", "width": "int", "height": "int"}, True),
        ("get_monitors", win_t.get_monitors, "List connected monitors: id, geometry, primary, left/right/main/other roles", {}, True),
        ("get_windows_by_monitor", win_t.get_windows_by_monitor, "List windows on a monitor (id or left/right/main/other/screen N)", {"monitor": "str"}, True),
        ("press_key", input_tools.press_key, "Press a single key", {"key": "str"}, True),
        ("hotkey", input_tools.hotkey, "Press a key combo (ctrl c, alt tab…)", {"keys": "str"}, True),
        ("type_text", input_tools.type_text, "Type text into the focused app", {"text": "str"}, True),
        ("scroll", input_tools.scroll, "Scroll in an app/window", {"direction": "str", "app": "str"}, True),
        ("open_file", files_tools.open_file, "Open a file with the default app", {"path": "str"}, True),
        ("open_folder", files_tools.open_folder, "Open a folder in Explorer", {"location": "str"}, True),
        ("search_files", files_tools.search_files, "Search local files by name under Desktop/Documents/…", {"query": "str"}, True),
        # Perception / browser / shell
        ("get_ui_tree", uia_tools.get_ui_tree, "Inspect foreground UI tree (name, type, automationId, bounds)", {"depth": "int", "limit": "int"}, True),
        ("get_active_window_elements", uia_tools.get_active_window_elements, "List interactive elements in the active window", {"limit": "int"}, True),
        ("find_ui_element", uia_tools.find_ui_element, "Find/rank UI element by name (e.g. Settings)", {"name": "str", "control_type": "str"}, True),
        ("click_ui_element", uia_tools.click_ui_element, "Click best-ranked UI element by semantic name", {"name": "str", "control_type": "str"}, True),
        ("get_element_text", uia_tools.get_element_text, "Read text/value from a UI element", {"name": "str"}, True),
        ("get_element_bounds", uia_tools.get_element_bounds, "Get bounding rectangle of a UI element", {"name": "str"}, True),
        ("capture_screen", screen_tools.capture_screen, "Capture primary or all monitors (resized)", {"all": "bool"}, True),
        ("capture_monitor", screen_tools.capture_monitor, "Capture a monitor (id or left/right/main/screen N) to PNG", {"monitor": "str"}, True),
        ("get_cursor_position", screen_tools.get_cursor_position, "Get mouse cursor x,y + monitor", {}, True),
        ("get_active_window_screenshot", screen_tools.get_active_window_screenshot, "Screenshot the foreground window only", {}, True),
        ("ocr_image", screen_tools.ocr_image, "OCR an image path or live capture (local RapidOCR)", {"path": "str"}, True),
        ("detect_text_regions", screen_tools.detect_text_regions, "OCR text boxes with coordinates", {"path": "str"}, True),
        ("ocr_screen", screen_tools.ocr_screen, "OCR current screen/window", {"monitor": "int"}, True),
        ("analyze_screen", screen_tools.analyze_screen, "Perceive screen: UIA→OCR→local VLM ScreenContext", {"request": "str", "monitor": "int"}, True),
        ("get_screen_context", screen_tools.get_screen_context, "Structured ScreenContext for planner", {"monitor": "int"}, True),
        # Phase 4 browser (DOM/a11y first)
        ("browser_open", browser_tools.browser_open, "Open site/URL in controlled Playwright Chrome", {"site": "str"}, True),
        ("browser_navigate", browser_tools.browser_navigate, "Navigate to a URL", {"url": "str"}, True),
        ("browser_search", browser_tools.browser_search, "Generic site search via DOM/search URL", {"site": "str", "query": "str"}, True),
        ("browser_get_page", browser_tools.browser_get_page, "Read page title/url/text + links", {}, True),
        ("browser_read_page", browser_tools.browser_read_page, "Alias of browser_get_page", {}, True),
        ("browser_get_elements", browser_tools.browser_get_elements, "List interactive DOM/a11y elements", {"limit": "int"}, True),
        ("browser_find_element", browser_tools.browser_find_element, "Find/rank DOM element by name/role", {"name": "str", "role": "str"}, True),
        ("browser_click", browser_tools.browser_click, "Click DOM element by name or index", {"name": "str", "index": "int"}, True),
        ("browser_type", browser_tools.browser_type, "Type into search/textbox (optional submit)", {"text": "str", "submit": "bool"}, True),
        ("browser_scroll", browser_tools.browser_scroll, "Scroll the page", {"direction": "str"}, True),
        ("browser_back", browser_tools.browser_back, "Browser history back", {}, True),
        ("browser_forward", browser_tools.browser_forward, "Browser history forward", {}, True),
        ("browser_get_tabs", browser_tools.browser_get_tabs, "List open tabs", {}, True),
        ("browser_switch_tab", browser_tools.browser_switch_tab, "Switch to tab by index", {"index": "int"}, True),
        ("browser_close_tab", browser_tools.browser_close_tab, "Close tab (current or index)", {"index": "int"}, True),
        ("browser_research", browser_tools.browser_research, "Search + open pages + summarize (sources in state)", {"query": "str", "site": "str"}, True),
        ("run_powershell", shell_tools.run_powershell, "Validated PowerShell only", {"command": "str"}, False),
        ("web_search_summarize", web_tools.web_search_summarize, "HTTP scrape search + local summarize", {"query": "str"}, False),
    ]
    for name, fn, desc, schema, overwrite in extras:
        def _make(f):
            return lambda a, _f=f: _f(a or {})

        register(
            name,
            _make(fn),
            description=desc,
            args_schema=schema,
            risk=DEFAULT_RISK.get(name, "low"),
            overwrite=overwrite,
        )


def reset_for_tests() -> None:
    global _BOOTSTRAPPED
    _REGISTRY.clear()
    _BOOTSTRAPPED = False
