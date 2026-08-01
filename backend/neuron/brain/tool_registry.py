"""Tool registry — name → schema, handler, risk, control methods.

Planner never touches the OS; it only emits action names registered here.
V3.5: typed params, validation, aliases, control_methods, planner visibility.
Only registered tools may execute — no arbitrary Python/shell from the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from neuron.catalog import DEFAULT_RISK, LEGACY_EXECUTORS, NEW_TOOLS

Handler = Callable[[dict], Any]

# Never expose these to the LLM planner (registered only for gated/legacy paths).
_PLANNER_HIDDEN = frozenset({
    "run_shell",
    "run_powershell",
    "eval",
    "exec",
    "python",
    "subprocess",
})

# Canonical alias → registered tool
_ALIASES: dict[str, str] = {
    "focus_window": "focus_app",
    "open_url": "browser_navigate",
    "read_page": "browser_read_page",
    "find_file": "search_files",
    "inspect_screen": "analyze_screen",
    "press_keys": "press_keys",  # keep identity; hotkey is separate
}


@dataclass
class ToolSpec:
    name: str
    handler: Handler
    description: str = ""
    args_schema: dict = field(default_factory=dict)  # planner display
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    # params[name] = {type: str|int|float|bool|any, required: bool, description?: str}
    risk: str = "low"  # safe | low | medium | high | confirm | blocked
    verify: str = ""  # optional verify hint for verifier
    control_methods: list[str] = field(default_factory=list)
    # e.g. ["dom","uia","filesystem","api","perception","input","coords"]
    planner_visible: bool = True
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": dict(self.args_schema),
            "params": dict(self.params),
            "risk": self.risk,
            "verify": self.verify,
            "control_methods": list(self.control_methods),
            "planner_visible": self.planner_visible,
            "aliases": list(self.aliases),
        }


_REGISTRY: dict[str, ToolSpec] = {}
_BOOTSTRAPPED = False


def register(
    name: str,
    handler: Handler,
    *,
    description: str = "",
    args_schema: dict | None = None,
    params: dict[str, dict[str, Any]] | None = None,
    risk: str | None = None,
    verify: str = "",
    control_methods: list[str] | None = None,
    planner_visible: bool | None = None,
    aliases: tuple[str, ...] | list[str] | None = None,
    overwrite: bool = False,
) -> None:
    if name in _REGISTRY and not overwrite:
        return
    schema = dict(args_schema or {})
    typed = dict(params or {})
    if not typed and schema:
        # Promote legacy display schema → typed params (all optional str-ish)
        for k, v in schema.items():
            typed[k] = {
                "type": _infer_type_label(str(v)),
                "required": False,
                "description": str(v),
            }
    if not schema and typed:
        schema = {
            k: (v.get("description") or v.get("type") or "any")
            for k, v in typed.items()
        }
    visible = planner_visible
    if visible is None:
        visible = name not in _PLANNER_HIDDEN
    alias_t = tuple(aliases or ())
    methods = list(control_methods or [])
    _REGISTRY[name] = ToolSpec(
        name=name,
        handler=handler,
        description=description or name,
        args_schema=schema,
        params=typed,
        risk=risk or DEFAULT_RISK.get(name, "confirm"),
        verify=verify,
        control_methods=methods,
        planner_visible=visible,
        aliases=alias_t,
    )
    for a in alias_t:
        if a and a != name:
            _ALIASES[a] = name


def unregister(name: str) -> bool:
    """Remove a tool registration (plugin unload). Returns True if removed."""
    key = resolve_name(name) if name else ""
    target = key if key in _REGISTRY else (name or "")
    if target not in _REGISTRY:
        return False
    _REGISTRY.pop(target, None)
    for alias, dest in list(_ALIASES.items()):
        if dest == target or alias == target:
            _ALIASES.pop(alias, None)
    return True


def _infer_type_label(hint: str) -> str:
    h = (hint or "").lower()
    if "int" in h:
        return "int"
    if "float" in h or "number" in h:
        return "float"
    if "bool" in h:
        return "bool"
    if "str" in h or "path" in h or "url" in h or "name" in h:
        return "str"
    return "any"


def resolve_name(name: str) -> str:
    """Map alias → canonical registered name."""
    n = (name or "").strip()
    if not n:
        return n
    return _ALIASES.get(n, n)


def get(name: str) -> ToolSpec | None:
    ensure_bootstrapped()
    canon = resolve_name(name)
    return _REGISTRY.get(canon) or _REGISTRY.get(name)


def is_registered(name: str) -> bool:
    return get(name) is not None


def all_tools() -> list[ToolSpec]:
    ensure_bootstrapped()
    return list(_REGISTRY.values())


def names() -> list[str]:
    ensure_bootstrapped()
    return sorted(_REGISTRY.keys())


def validate_args(
    name: str, args: dict | None = None
) -> tuple[bool, str, dict[str, Any]]:
    """
    Validate / coerce arguments against the tool's typed param schema.

    Returns (ok, error_message, coerced_args).
    Unknown tools → ok=False.
    """
    ensure_bootstrapped()
    spec = get(name)
    if not spec:
        return False, f"Unknown tool: {name}", {}
    raw = dict(args or {})
    params = spec.params or {}
    if not params:
        return True, "", raw

    coerced: dict[str, Any] = dict(raw)
    # Map aliases → canonical keys
    for key, meta in params.items():
        if key in coerced and coerced[key] not in (None, ""):
            continue
        for a in meta.get("aliases") or ():
            if a in raw and raw[a] not in (None, ""):
                coerced[key] = raw[a]
                break
    # Required
    for key, meta in params.items():
        if not meta.get("required"):
            continue
        if key not in coerced or coerced[key] in (None, ""):
            return False, f"Missing required argument '{key}' for {spec.name}", raw

    # Type coerce known params
    for key, meta in params.items():
        if key not in coerced or coerced[key] is None or coerced[key] == "":
            continue
        t = (meta.get("type") or "any").lower()
        val = coerced[key]
        try:
            if t == "int":
                coerced[key] = int(val)
            elif t == "float":
                coerced[key] = float(val)
            elif t == "bool":
                if isinstance(val, bool):
                    pass
                elif str(val).strip().lower() in ("1", "true", "yes", "on"):
                    coerced[key] = True
                elif str(val).strip().lower() in ("0", "false", "no", "off"):
                    coerced[key] = False
                else:
                    return False, f"Invalid bool for '{key}': {val!r}", raw
            elif t == "str":
                coerced[key] = str(val)
        except (TypeError, ValueError):
            return False, f"Invalid {t} for '{key}': {val!r}", raw
    return True, "", coerced


def execute(
    name: str,
    args: dict | None = None,
    *,
    confirmed: bool = False,
    skip_policy: bool = False,
) -> Any:
    """
    Run a registered tool only. Raises ValueError for unknown / invalid args.
    Does not allow arbitrary Python or shell outside registered handlers.
    """
    ensure_bootstrapped()
    spec = get(name)
    if not spec:
        raise ValueError(f"Unknown tool: {name} (only registered tools may execute)")
    ok, err, coerced = validate_args(spec.name, args)
    if not ok:
        raise ValueError(err or f"Invalid arguments for {name}")
    if not skip_policy:
        try:
            from neuron.safety import policy
            allowed, reason = policy.allow(
                spec.name, coerced, confirmed=confirmed or bool(coerced.get("confirmed"))
            )
            if not allowed:
                raise PermissionError(reason or f"Not allowed: {spec.name}")
        except PermissionError:
            raise
        except Exception:
            pass
    try:
        result = spec.handler(coerced)
        ok = True
        detail = ""
        if hasattr(result, "success"):
            ok = bool(result.success)
            detail = str(getattr(result, "message", "") or "")
        try:
            from neuron.learning_engine import observe_tool
            observe_tool(spec.name, coerced, ok=ok, detail=detail)
        except Exception:
            pass
        try:
            from neuron.memory_engine import observe_tool as mem_observe_tool
            mem_observe_tool(spec.name, coerced, ok=ok)
        except Exception:
            pass
        return result
    except Exception as exc:
        try:
            from neuron.learning_engine import observe_tool
            observe_tool(spec.name, coerced, ok=False, detail=str(exc))
        except Exception:
            pass
        try:
            from neuron.memory_engine import observe_tool as mem_observe_tool
            mem_observe_tool(spec.name, coerced, ok=False)
        except Exception:
            pass
        raise


def tools_doc(limit: int = 80) -> str:
    """Compact card for the LLM planner — single source of truth."""
    ensure_bootstrapped()
    lines = [
        "TOOLS (call with {\"tool\":\"name\",\"arguments\":{...}}):",
        "Prefer structured tools. Coordinate mouse is LAST resort.",
        "Only registered tools below may execute. No shell/Python/eval.",
    ]
    visible = [
        s for s in sorted(_REGISTRY.values(), key=lambda s: s.name)
        if s.planner_visible and s.name not in _PLANNER_HIDDEN
    ]
    for spec in visible[:limit]:
        args = ",".join(f"{k}:{v}" for k, v in (spec.args_schema or {}).items()) if spec.args_schema else ""
        bit = "{" + args + "}" if args else "{}"
        methods = (" methods=" + "+".join(spec.control_methods)) if spec.control_methods else ""
        lines.append(
            f"- {spec.name}{bit} risk={spec.risk}{methods} — {spec.description}"
        )
    lines.append(
        "HIERARCHY: API/CLI → browser DOM → UI Automation → OCR → vision → coords."
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
        "UI: click_element / click_ui_element go through Element Resolver "
        "(DOM → UIA → OCR → Vision → mouse). Prefer that over raw click / move_mouse / computer_use."
    )
    lines.append(
        "DOMAIN SKILLS: prefer youtube.search / windows.move_to_monitor / "
        "spotify.play / discord.open_channel / files.find / blender.open_project "
        "over ad-hoc multi-step plans when they match."
    )
    try:
        from neuron.safety.levels import tier_prompt
        lines.append(tier_prompt())
    except Exception:
        pass
    lines.append(
        "LEARNING: 'learn how I …' records a PROCEDURE skill (clicks→steps). "
        "Never rewrite NEURON source. Reuse with the saved phrase or run_procedure{id}."
    )
    return "\n".join(lines)


def ensure_bootstrapped() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    _bootstrap_legacy()
    _bootstrap_new()
    _bootstrap_skills()
    _bootstrap_procedures()
    _bootstrap_v35_primitives()
    _bootstrap_plugins()


def _bootstrap_plugins() -> None:
    """Plugin SDK — discover builtin + config paths, register manager tools."""
    try:
        from neuron.plugins.manager import (
            bootstrap,
            tool_plugin_docs,
            tool_plugin_reload,
            tool_plugins_list,
        )
        register(
            "plugins_list",
            tool_plugins_list,
            description="List installed plugins, versions, and intents",
            args_schema={},
            risk="safe",
            overwrite=True,
            planner_visible=True,
        )
        register(
            "plugin_reload",
            tool_plugin_reload,
            description="Hot-reload a plugin by id",
            args_schema={"id": "str"},
            risk="safe",
            overwrite=True,
            planner_visible=False,
        )
        register(
            "plugin_docs",
            tool_plugin_docs,
            description="Read a plugin README / documentation",
            args_schema={"id": "str"},
            risk="safe",
            overwrite=True,
            planner_visible=False,
        )
        loaded = bootstrap()
        ok_n = sum(1 for p in loaded if p.get("enabled"))
        print(f"[tools] plugins loaded {ok_n}/{len(loaded)}", flush=True)
    except Exception as exc:
        print(f"[tools] plugins bootstrap skipped: {exc}", flush=True)


def _bootstrap_skills() -> None:
    try:
        from neuron.skills.registry import bootstrap_skills
        n = bootstrap_skills(register)
        print(f"[tools] registered {n} domain skills", flush=True)
    except Exception as exc:
        print(f"[tools] skills bootstrap skipped: {exc}", flush=True)


def _bootstrap_procedures() -> None:
    """Phase 9 learned procedures + run_procedure tool."""
    try:
        from neuron.learning.procedures import bootstrap_learned_skills, run_procedure_tool
        register(
            "run_procedure",
            run_procedure_tool,
            description="Run a learned procedure by id or matching phrase",
            args_schema={"id": "str", "query": "str"},
            risk="safe",
            overwrite=True,
        )
        n = bootstrap_learned_skills()
        print(f"[tools] registered {n} learned/builtin procedures", flush=True)
    except Exception as exc:
        print(f"[tools] procedures bootstrap skipped: {exc}", flush=True)


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
        "click_element": {"name": "str"},
        "find_element": {"name": "str"},
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
        "click_ui_element": "Click via Element Resolver (DOM→UIA→OCR→Vision)",
        "click_element": "Alias of click_ui_element — semantic click(\"Search\")",
        "find_element": "Resolve element without clicking (reports source + coords)",
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
            risk=DEFAULT_RISK.get(name, "confirm"),
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
        ("click_ui_element", uia_tools.click_ui_element, "Click via Element Resolver: DOM→UIA→OCR→Vision→mouse", {"name": "str", "control_type": "str"}, True),
        ("click_element", uia_tools.click_element, "Semantic click(\"Search\") via Element Resolver cascade", {"name": "str", "index": "int"}, True),
        ("find_element", uia_tools.find_element, "Resolve click target without acting (source + coords)", {"name": "str"}, True),
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
        ("run_powershell", shell_tools.run_powershell, "Validated PowerShell only (not for LLM planner)", {"command": "str"}, False),
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
            risk=DEFAULT_RISK.get(name, "safe"),
            overwrite=overwrite,
            planner_visible=(name not in _PLANNER_HIDDEN),
            control_methods=_default_methods(name),
        )

    try:
        from neuron.screen.engine import tool_screen_understand
        register(
            "screen_understand",
            tool_screen_understand,
            description="Screen Understanding: screenshot+OCR+UIA+grounded click/read/scroll",
            args_schema={"request": "str", "query": "str"},
            risk="safe",
            overwrite=True,
            planner_visible=True,
            control_methods=["uia", "ocr", "perception"],
        )
    except Exception as exc:
        print(f"[tools] screen_understand skipped: {exc}", flush=True)

    try:
        from neuron.taskplan.engine import tool_run_task_workflow
        from neuron.taskplan.file_ops import task_move_files, task_zip_folder
        register(
            "run_task_workflow",
            tool_run_task_workflow,
            description="Task Planning Engine: multi-step desktop workflows with verify/recover",
            args_schema={"request": "str", "goal": "str", "confirmed": "bool"},
            risk="safe",
            overwrite=True,
            planner_visible=True,
            control_methods=["uia", "api", "filesystem"],
        )
        register(
            "task_move_files",
            lambda a: task_move_files(a or {}),
            description="Move files matching a pattern into a folder (desktop workflows)",
            args_schema={"pattern": "str", "dest": "str", "location": "str"},
            risk="confirm",
            overwrite=True,
            planner_visible=True,
            control_methods=["filesystem"],
        )
        register(
            "task_zip_folder",
            lambda a: task_zip_folder(a or {}),
            description="Zip a folder on Desktop/Documents",
            args_schema={"name": "str", "location": "str"},
            risk="confirm",
            overwrite=True,
            planner_visible=True,
            control_methods=["filesystem"],
        )
    except Exception as exc:
        print(f"[tools] taskplan tools skipped: {exc}", flush=True)

    try:
        from neuron.computer_use.agent import tool_computer_use_agent
        from neuron.computer_use.primitives import tool_drag_drop, tool_upload_file
        register(
            "computer_use_agent",
            tool_computer_use_agent,
            description="Computer Use Agent: operate any Windows app (click/type/drag/upload/forms)",
            args_schema={"goal": "str", "request": "str", "confirmed": "bool"},
            risk="confirm",
            overwrite=True,
            planner_visible=True,
            control_methods=["uia", "ocr", "perception", "input"],
        )
        register(
            "drag_drop",
            tool_drag_drop,
            description="Drag mouse from (x1,y1) to (x2,y2)",
            args_schema={"x1": "int", "y1": "int", "x2": "int", "y2": "int"},
            risk="confirm",
            overwrite=True,
            planner_visible=True,
            control_methods=["input"],
        )
        register(
            "upload_file",
            tool_upload_file,
            description="Type a file path into an Open/Upload dialog",
            args_schema={"path": "str", "method": "str"},
            risk="confirm",
            overwrite=True,
            planner_visible=True,
            control_methods=["input", "filesystem"],
        )
    except Exception as exc:
        print(f"[tools] computer_use tools skipped: {exc}", flush=True)

    try:
        from neuron.learning_engine import tool_learning_status
        register(
            "learning_status",
            tool_learning_status,
            description="Show Learning Engine favorites, rankings, and habit predictions",
            args_schema={},
            risk="safe",
            overwrite=True,
            planner_visible=True,
            control_methods=["api"],
        )
    except Exception as exc:
        print(f"[tools] learning_engine skipped: {exc}", flush=True)

    try:
        from neuron.memory_engine import tool_memory_status
        register(
            "memory_status",
            tool_memory_status,
            description="Long-term memory stats: episodic/semantic/project/pinned",
            args_schema={},
            risk="safe",
            overwrite=True,
            planner_visible=True,
            control_methods=["api"],
        )
    except Exception as exc:
        print(f"[tools] memory_engine skipped: {exc}", flush=True)


def _default_methods(name: str) -> list[str]:
    n = name or ""
    if n.startswith("browser_") or n in ("open_website", "search_web", "search_site"):
        return ["dom", "playwright"]
    if n in (
        "open_app", "close_app", "focus_app", "move_window", "move_window_to_monitor",
        "get_windows", "get_active_window", "minimize_app", "maximize_app",
        "click_ui_element", "find_ui_element", "get_ui_tree", "get_active_window_elements",
    ):
        return ["uia", "api"]
    if n in ("open_file", "open_folder", "search_files", "create_file", "create_folder"):
        return ["filesystem"]
    if n in ("click_element", "find_element"):
        return ["dom", "uia", "ocr", "perception", "coords"]
    if n in ("analyze_screen", "get_screen_context", "ocr_screen", "ocr_image"):
        return ["uia", "ocr", "perception"]
    if n in ("type_text", "press_key", "hotkey", "scroll", "click", "press_keys"):
        return ["input"]
    if n in ("volume", "media", "wait"):
        return ["api"]
    if n in ("run_shell", "run_powershell"):
        return ["cli"]
    return []


def _bootstrap_v35_primitives() -> None:
    """Ensure V3.5 canonical primitives exist as aliases / thin wrappers over existing actions."""
    from neuron.windows.result import ok as _ok, fail as _fail

    # Hide shell tools from planner after legacy bootstrap
    for hidden in _PLANNER_HIDDEN:
        spec = _REGISTRY.get(hidden)
        if spec:
            spec.planner_visible = False

    # --- speak ---
    def _speak(args: dict | None = None):
        args = args or {}
        text = (args.get("text") or args.get("say") or args.get("message") or "").strip()
        if not text:
            return _fail("Need text to speak.", method="speak")
        try:
            import memory
            memory.log("neuron", text)
        except Exception:
            pass
        return _ok(text, state={"spoken": text}, method="speak")

    register(
        "speak",
        _speak,
        description="Speak / surface a short reply to the user",
        params={
            "text": {"type": "str", "required": True, "description": "utterance", "aliases": ("say", "message")},
        },
        risk="safe",
        control_methods=["api"],
        overwrite=True,
    )

    # --- wait (ensure typed schema) ---
    def _wait(args: dict | None = None):
        args = args or {}
        try:
            import actions
            sec = float(args.get("seconds", args.get("sec", 1)) or 1)
            return actions.wait(sec)
        except Exception as exc:
            return f"Wait failed: {exc}"

    if "wait" not in _REGISTRY:
        register(
            "wait",
            _wait,
            description="Pause briefly before the next step",
            params={"seconds": {"type": "float", "required": False, "description": "seconds to wait"}},
            risk="safe",
            control_methods=["api"],
        )
    else:
        # Enrich schema without replacing handler
        spec = _REGISTRY["wait"]
        if not spec.params:
            spec.params = {"seconds": {"type": "float", "required": False}}
        if not spec.control_methods:
            spec.control_methods = ["api"]

    # --- verify ---
    def _verify(args: dict | None = None):
        args = args or {}
        expect = (args.get("expect") or args.get("expected") or args.get("goal") or "").strip()
        try:
            from neuron.brain.computer_state import capture
            cs = capture(deep=False, remember=False)
            blob = ""
            if hasattr(cs, "looking_at"):
                blob = f"{cs.looking_at()} {getattr(cs, 'focused_window_title', '')} {getattr(cs, 'browser_url', '')}"
            else:
                blob = str(cs)
            if expect and expect.lower() not in blob.lower():
                return _fail(
                    f"Not verified (want '{expect}'). Seeing: {blob[:120]}",
                    state={"expect": expect, "observed": blob[:300]},
                    method="verify",
                )
            return _ok(
                f"Verified{': ' + expect if expect else ''}.",
                state={"expect": expect, "observed": blob[:300], "verified": True},
                method="verify",
            )
        except Exception as exc:
            return _fail(f"Verify failed: {exc}", method="verify")

    register(
        "verify",
        _verify,
        description="Check current computer state against an expectation",
        params={"expect": {"type": "str", "required": False, "aliases": ("expected", "goal")}},
        risk="safe",
        control_methods=["api", "uia"],
        overwrite=True,
    )

    # --- click primitive: semantic name → Element Resolver; else last-resort coords/button ---
    def _click(args: dict | None = None):
        args = dict(args or {})
        if args.get("name") or args.get("text") or args.get("query") or args.get("index") is not None:
            from neuron.tools import uia_tools
            return uia_tools.click_element(args)
        if args.get("x") is not None and args.get("y") is not None:
            try:
                import pyautogui
                pyautogui.click(int(args["x"]), int(args["y"]))
                return _ok(f"Clicked at ({args['x']},{args['y']}).", method="coords")
            except Exception as exc:
                return _fail(str(exc), method="coords")
        from neuron.tools import input_tools
        return input_tools.click(args)

    register(
        "click",
        _click,
        description="Click: semantic element (preferred) or x,y last resort",
        params={
            "name": {"type": "str", "required": False},
            "index": {"type": "int", "required": False},
            "x": {"type": "int", "required": False},
            "y": {"type": "int", "required": False},
        },
        risk="safe",
        control_methods=["dom", "uia", "ocr", "perception", "coords"],
        overwrite=True,
    )

    # Canonical aliases → existing tools (handlers shared via resolve_name)
    alias_map = {
        "focus_window": "focus_app",
        "open_url": "browser_navigate",
        "read_page": "browser_read_page",
        "find_file": "search_files",
        "inspect_screen": "analyze_screen",
    }
    for alias, target in alias_map.items():
        _ALIASES[alias] = target
        # Also register alias name as a visible synonym entry pointing at same handler
        target_spec = _REGISTRY.get(target)
        if target_spec and alias not in _REGISTRY:
            register(
                alias,
                target_spec.handler,
                description=f"Alias of {target}: {target_spec.description}",
                args_schema=dict(target_spec.args_schema),
                params=dict(target_spec.params),
                risk=target_spec.risk,
                control_methods=list(target_spec.control_methods),
                planner_visible=True,
                overwrite=True,
            )

    # Enrich core primitives with required-param schemas where missing
    enrich = {
        "open_app": {
            "params": {"name": {"type": "str", "required": True, "aliases": ("application", "app")}},
            "methods": ["api", "uia"],
        },
        "close_app": {
            "params": {"name": {"type": "str", "required": True}},
            "methods": ["api", "uia"],
        },
        "focus_app": {
            "params": {"name": {"type": "str", "required": True}},
            "methods": ["api", "uia"],
        },
        "move_window": {
            "params": {
                "title": {"type": "str", "required": False},
                "monitor": {"type": "str", "required": False},
                "x": {"type": "int", "required": False},
                "y": {"type": "int", "required": False},
            },
            "methods": ["api", "uia"],
        },
        "type_text": {
            "params": {"text": {"type": "str", "required": True}},
            "methods": ["input"],
        },
        "press_key": {
            "params": {"key": {"type": "str", "required": True}},
            "methods": ["input"],
        },
        "hotkey": {
            "params": {"keys": {"type": "str", "required": True}},
            "methods": ["input"],
        },
        "scroll": {
            "params": {"direction": {"type": "str", "required": False}},
            "methods": ["input", "dom"],
        },
        "browser_search": {
            "params": {
                "query": {"type": "str", "required": True},
                "site": {"type": "str", "required": False},
            },
            "methods": ["dom", "playwright"],
        },
        "browser_navigate": {
            "params": {"url": {"type": "str", "required": True, "aliases": ("site",)}},
            "methods": ["dom", "playwright"],
        },
        "open_file": {
            "params": {"path": {"type": "str", "required": True}},
            "methods": ["filesystem"],
        },
        "search_files": {
            "params": {"query": {"type": "str", "required": True}},
            "methods": ["filesystem"],
        },
        "find_element": {
            "params": {"name": {"type": "str", "required": True}},
            "methods": ["dom", "uia", "ocr"],
        },
        "click_element": {
            "params": {
                "name": {"type": "str", "required": False},
                "index": {"type": "int", "required": False},
            },
            "methods": ["dom", "uia", "ocr", "perception", "coords"],
        },
        "volume": {
            "params": {"action": {"type": "str", "required": False}},
            "methods": ["api"],
        },
    }
    for name, meta in enrich.items():
        spec = _REGISTRY.get(name)
        if not spec:
            continue
        if meta.get("params"):
            merged = dict(spec.params or {})
            merged.update(meta["params"])
            spec.params = merged
            if not spec.args_schema:
                spec.args_schema = {
                    k: v.get("type", "any") for k, v in merged.items()
                }
        if meta.get("methods") and not spec.control_methods:
            spec.control_methods = list(meta["methods"])


def reset_for_tests() -> None:
    global _BOOTSTRAPPED
    _REGISTRY.clear()
    _BOOTSTRAPPED = False
    # Keep canonical alias table; per-tool aliases re-added on bootstrap
