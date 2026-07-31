"""CapabilityRouter — map utterances to stable capability IDs → tools.

V3.2/V3.5: routes high-reliability workflows to existing registry tools /
domain skills. Chooses the strongest control method for the domain:

  browser → DOM / Playwright
  Windows app → UI Automation
  files → filesystem APIs
  supported integration → API / CLI
  unknown UI → perception + input
  coordinates → last resort

Unsupported requests return ok=False so V2 AgentLoop LLM or legacy rules
handle them. Deterministic fast paths (volume, skip-ad, open app) never
require LLM planning.

Does NOT execute actions. Does NOT replace Intent, Planner, or AgentLoop.
Only emits tool names that exist in ToolRegistry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


METHOD_RANK = (
    "api",
    "cli",
    "filesystem",
    "dom",
    "playwright",
    "uia",
    "perception",
    "ocr",
    "input",
    "coords",
)


@dataclass
class Capability:
    """Stable capability identity + concrete tool binding."""

    id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    source: str = ""  # pattern | intent | skill | method
    description: str = ""
    control_method: str = ""
    fallback_methods: list[str] = field(default_factory=list)


@dataclass
class RouteResult:
    ok: bool
    capability: Capability | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    control_method: str = ""

    def as_plan(self, say: str = "") -> dict[str, Any] | None:
        if not self.ok or not self.steps:
            return None
        return {"say": say or "", "steps": list(self.steps)}


_CAPABILITY_TOOLS: dict[str, str] = {
    "youtube.skip_ad": "skip_ad",
    "youtube.home": "youtube_home",
    "youtube.search": "search_site",
    "youtube.play_first": "play_result",
    "youtube.play_second": "play_result",
    "youtube.fullscreen": "fullscreen",
    "youtube.pause": "ensure_playback",
    "youtube.play": "ensure_playback",
    "windows.open_app": "open_app",
    "windows.focus_app": "focus_app",
    "windows.close_app": "close_app",
    "windows.move_to_monitor": "move_window_to_monitor",
    "multi_app.workflow": "open_app",
    "browser.open": "open_website",
    "browser.search": "search_web",
    "browser.open_url": "browser_navigate",
    "files.open_downloads": "open_folder",
    "files.find": "search_files",
    "files.open": "open_file",
    "input.type": "type_text",
    "input.copy": "press_keys",
    "input.paste": "press_keys",
    "input.escape": "press_keys",
    "input.hotkey": "hotkey",
    "ui.scroll": "scroll",
    "ui.click": "click_element",
    "ui.find": "find_element",
    "ui.inspect": "analyze_screen",
    "system.volume": "volume",
    "system.wait": "wait",
    "system.speak": "speak",
    "system.verify": "verify",
    "procedure.run": "run_procedure",
}

_DOMAIN_METHODS: dict[str, list[str]] = {
    "browser": ["dom", "playwright", "perception", "coords"],
    "windows": ["api", "uia", "perception", "input", "coords"],
    "files": ["filesystem", "api"],
    "integration": ["api", "cli"],
    "youtube": ["api", "dom", "playwright"],
    "input": ["input", "uia"],
    "unknown_ui": ["perception", "uia", "ocr", "input", "coords"],
    "system": ["api"],
}


def choose_control_method(
    domain: str,
    *,
    browser_context: bool = False,
    available: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Pick the strongest available control method for a domain."""
    if browser_context and domain in ("unknown_ui", "windows", "ui"):
        domain = "browser"
    preferred = list(_DOMAIN_METHODS.get(domain, _DOMAIN_METHODS["unknown_ui"]))
    if available:
        avail = set(available)
        preferred = [m for m in preferred if m in avail] or preferred
    if not preferred:
        return "coords", []
    return preferred[0], preferred[1:]


def _browser_context() -> bool:
    try:
        from neuron.brain.computer_state import get_last_state, capture
        cs = get_last_state() or capture(deep=False, remember=False)
        if cs and (getattr(cs, "browser_url", None) or "").strip():
            return True
        scene = (getattr(cs, "scene", "") or "").lower()
        if scene in ("youtube", "browser"):
            return True
        app = (cs.looking_at() if cs else "") or ""
        if any(b in app.lower() for b in ("chrome", "edge", "firefox", "brave")):
            return True
    except Exception:
        pass
    try:
        import browser
        if browser.current_url():
            return True
    except Exception:
        pass
    return False


def _registry_has(tool: str) -> bool:
    try:
        from neuron.brain import tool_registry
        return tool_registry.is_registered(tool)
    except Exception:
        return True


def _step(tool: str, args: dict | None = None, **extra) -> dict[str, Any]:
    s: dict[str, Any] = {"tool": tool, "arguments": dict(args or {})}
    s.update(extra)
    return s


def _result(cap: Capability, *steps: dict) -> RouteResult:
    valid_steps = []
    for st in steps:
        tool = st.get("tool") or st.get("action") or ""
        if tool and not _registry_has(tool):
            continue
        valid_steps.append(st)
    if not valid_steps:
        return RouteResult(ok=False, reason=f"tool_not_registered:{cap.tool}")
    return RouteResult(
        ok=True,
        capability=cap,
        steps=valid_steps,
        reason=f"routed:{cap.id}",
        control_method=cap.control_method,
    )


def _domain_for_cap(cid: str) -> str:
    if cid.startswith("browser."):
        return "browser"
    if cid.startswith("youtube."):
        return "youtube"
    if cid.startswith("windows."):
        return "windows"
    if cid.startswith("files."):
        return "files"
    if cid.startswith("input."):
        return "input"
    if cid.startswith("ui."):
        return "unknown_ui"
    if cid.startswith("system."):
        return "system"
    return "integration"


def _cap(
    cid: str,
    args: dict | None = None,
    *,
    conf: float,
    source: str,
    desc: str = "",
    domain: str = "",
    tool: str | None = None,
) -> Capability:
    t = tool or _CAPABILITY_TOOLS.get(cid, cid.replace(".", "_"))
    method, fallbacks = choose_control_method(
        domain or _domain_for_cap(cid),
        browser_context=_browser_context(),
    )
    if cid in ("ui.click", "ui.find") and method in ("dom", "playwright"):
        t = "browser_click" if cid == "ui.click" else "browser_find_element"
    return Capability(
        id=cid,
        tool=t,
        args=dict(args or {}),
        confidence=conf,
        source=source,
        description=desc or cid,
        control_method=method,
        fallback_methods=fallbacks,
    )


_WEBSITES = {
    "youtube", "yt", "gmail", "google", "maps", "github", "netflix",
    "reddit", "twitter", "facebook", "instagram",
}


def _route_patterns(text: str) -> RouteResult | None:
    t = (text or "").strip().lower()
    if not t:
        return None

    # V3.8 — multi-app staged workflows (before single-action patterns)
    try:
        from neuron.v3.multi_app import compose_multi_app_plan, looks_multi_app
        if looks_multi_app(t):
            plan = compose_multi_app_plan(t)
            if plan and plan.get("steps"):
                cap = _cap(
                    "multi_app.workflow",
                    {"stages": (plan.get("meta") or {}).get("stages") or []},
                    conf=0.9,
                    source="pattern",
                    desc="Multi-app staged workflow",
                    domain="windows",
                    tool="open_app",
                )
                steps = []
                for s in plan["steps"]:
                    steps.append(
                        _step(
                            s.get("action") or s.get("tool") or "",
                            s.get("args") or s.get("arguments") or {},
                            target=s.get("target") or "",
                            expected_result=s.get("expected_result") or "",
                            stage=s.get("stage") or "",
                        )
                    )
                hit = _result(cap, *steps)
                if hit.ok:
                    return hit
    except Exception:
        pass

    looks_like_multi = False
    try:
        from neuron.v3.multi_app import looks_multi_app as _lma
        looks_like_multi = _lma(t)
    except Exception:
        looks_like_multi = False

    # System: volume (deterministic — never LLM)
    if re.search(r"\bvolume\s+up\b|\bincrease\s+(?:the\s+)?volume\b|\blouder\b", t):
        cap = _cap(
            "system.volume", {"action": "up"}, conf=0.97, source="pattern",
            desc="Volume up", domain="system",
        )
        return _result(cap, _step("volume", {"action": "up"}, expected_result="volume up"))
    if re.search(
        r"\bvolume\s+down\b|\bdecrease\s+(?:the\s+)?volume\b|\bquieter\b|"
        r"\blower\s+(?:the\s+)?volume\b",
        t,
    ):
        cap = _cap(
            "system.volume", {"action": "down"}, conf=0.97, source="pattern",
            desc="Volume down", domain="system",
        )
        return _result(cap, _step("volume", {"action": "down"}, expected_result="volume down"))
    if re.search(r"\b(mute|unmute)\b", t) and not re.search(r"\bvideo\b", t):
        action = "unmute" if "unmute" in t else "mute"
        cap = _cap(
            "system.volume", {"action": action}, conf=0.95, source="pattern",
            desc=f"Volume {action}", domain="system",
        )
        return _result(cap, _step("volume", {"action": action}, expected_result=action))

    if re.search(
        r"\b(skip|close|dismiss)\b.{0,24}\b(ad|ads|add|adds|sad)\b"
        r"|\b(ad|ads|add|adds|sad)\b.{0,16}\b(skip|close|dismiss)\b"
        r"|\bskip(?:ping)?(?:\s+the|\s+this|\s+that)?\s+(?:ad|ads|add|adds|sad)\b",
        t,
    ):
        cap = _cap("youtube.skip_ad", conf=0.96, source="pattern", desc="Skip YouTube ad")
        return _result(cap, _step(cap.tool, {}, expected_result="ad skipped or no ad"))

    if re.search(
        r"\b(?:go\s+to|open|show|back\s+to)\s+(?:the\s+)?(?:youtube|yt)\s+"
        r"(?:home(?:\s*(?:page|screen))?|homepage|feed)\b"
        r"|\b(?:youtube|yt)\s+(?:home(?:\s*(?:page|screen))?|homepage)\b",
        t,
    ) and not re.search(r"\b(play|watch)\b", t):
        cap = _cap("youtube.home", conf=0.9, source="pattern")
        return _result(cap, _step(cap.tool, {}, expected_result="youtube homepage"))

    m = re.search(
        r"\b(?:search|find)\s+(?:on\s+)?(?:youtube|yt)\s+(?:for\s+)?(.+)$"
        r"|\b(?:youtube|yt)\s+search\s+(?:for\s+)?(.+)$",
        t,
    )
    if m:
        q = (m.group(1) or m.group(2) or "").strip(" .,!?")
        if q and len(q) >= 2:
            cap = _cap(
                "youtube.search",
                {"site": "youtube", "query": q},
                conf=0.9,
                source="pattern",
            )
            return _result(
                cap,
                _step(cap.tool, cap.args, expected_result="youtube search results"),
            )

    m = re.search(r"\bplay\s+(?:the\s+)?(first|1st|second|2nd|third|3rd)\s+video\b", t)
    if m:
        word = m.group(1)
        idx = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}[word]
        cid = "youtube.play_first" if idx == 1 else "youtube.play_second"
        if idx >= 3:
            cid = "youtube.play_first"
        cap = _cap(cid, {"index": idx}, conf=0.9, source="pattern")
        cap.id = f"youtube.play_result.{idx}"
        return _result(cap, _step("play_result", {"index": idx}, expected_result="video playing"))

    if re.search(r"\b(exit\s+)?fullscreen\b", t) and not re.search(r"\bwindow\b", t):
        exit_fs = bool(re.search(r"\bexit\b|\bleave\b|\bclose\s+fullscreen\b", t))
        cap = _cap("youtube.fullscreen", {"exit": exit_fs}, conf=0.85, source="pattern")
        return _result(cap, _step(cap.tool, {"exit": exit_fs}, expected_result="fullscreen toggled"))

    if re.search(r"\b(pause|stop)\s+(?:the\s+)?(?:video|youtube|yt|playback)\b", t):
        cap = _cap("youtube.pause", {"want": "pause"}, conf=0.88, source="pattern")
        return _result(cap, _step(cap.tool, {"want": "pause"}, expected_result="playback paused"))

    if re.search(r"\b(?:play|resume)\s+(?:the\s+)?(?:video|youtube|yt|playback)\b", t) and not re.search(
        r"\b(first|second|third|\d+|result)\b", t
    ):
        cap = _cap("youtube.play", {"want": "play"}, conf=0.85, source="pattern")
        return _result(cap, _step(cap.tool, {"want": "play"}, expected_result="playback playing"))

    m = re.search(r"\b(?:open|go\s+to|navigate\s+to)\s+(https?://\S+)\b", t)
    if m:
        url = m.group(1).rstrip(".,)")
        cap = _cap(
            "browser.open_url", {"url": url}, conf=0.92, source="pattern", domain="browser"
        )
        return _result(cap, _step("browser_navigate", {"url": url}, expected_result="page open"))

    m = re.search(r"\bopen\s+(downloads|documents|desktop|pictures|music|videos)\b", t)
    if m:
        loc = m.group(1)
        cap = _cap("files.open_downloads", {"location": loc}, conf=0.9, source="pattern")
        if loc != "downloads":
            cap.id = f"files.open_{loc}"
        return _result(cap, _step("open_folder", {"location": loc}, expected_result=f"{loc} open"))

    m = re.search(r"\b(?:find|search\s+for)\s+(?:a\s+|the\s+)?(.+?)\s+file(?:s)?\b", t)
    if m:
        q = m.group(1).strip()
        if q and q not in ("this", "that", "my"):
            cap = _cap("files.find", {"query": q}, conf=0.8, source="pattern")
            return _result(cap, _step(cap.tool, {"query": q}, expected_result="files listed"))

    if re.search(r"\b(inspect|analyze|what(?:'s| is) on)\s+(?:the\s+)?screen\b", t):
        cap = _cap("ui.inspect", {"request": t}, conf=0.85, source="pattern", domain="unknown_ui")
        return _result(cap, _step("analyze_screen", {"request": t}, expected_result="screen understood"))

    m = re.search(r"\b(?:click|press)\s+(?:the\s+)?(.+?)(?:\s+button)?$", t)
    if m and len(m.group(1).strip()) >= 2 and not re.search(r"\b(volume|ad|ads)\b", t):
        label = m.group(1).strip()
        if not _is_deixis(label) and label not in ("escape", "esc", "enter"):
            cap = _cap(
                "ui.click", {"name": label}, conf=0.82, source="pattern", domain="unknown_ui"
            )
            return _result(
                cap, _step(cap.tool, {"name": label}, expected_result=f"clicked {label}")
            )

    if re.fullmatch(r"(?:please\s+)?(?:copy(?:\s+(?:that|it|selection)?)?)", t):
        cap = _cap("input.copy", {"keys": "ctrl+c"}, conf=0.9, source="pattern")
        return _result(cap, _step("press_keys", {"keys": "ctrl+c"}, expected_result="copied"))
    if re.fullmatch(r"(?:please\s+)?(?:paste(?:\s+(?:that|it)?)?)", t):
        cap = _cap("input.paste", {"keys": "ctrl+v"}, conf=0.9, source="pattern")
        return _result(cap, _step("press_keys", {"keys": "ctrl+v"}, expected_result="pasted"))
    if re.search(r"\b(?:press\s+)?(?:escape|esc)\b|\bdismiss\s+(?:the\s+)?(?:popup|dialog)\b", t):
        cap = _cap("input.escape", {"keys": "esc"}, conf=0.9, source="pattern")
        return _result(cap, _step("press_keys", {"keys": "esc"}, expected_result="dismissed"))

    m = re.search(r"\bscroll\s+(up|down)\b", t)
    if m:
        tool = "browser_scroll" if _browser_context() else "scroll"
        if not _registry_has(tool):
            tool = "page_scroll" if _registry_has("page_scroll") else "scroll"
        cap = _cap(
            "ui.scroll", {"direction": m.group(1)}, conf=0.85, source="pattern",
            domain="browser" if tool.startswith("browser") else "input",
            tool=tool,
        )
        return _result(
            cap,
            _step(tool, {"direction": m.group(1)}, expected_result=f"scrolled {m.group(1)}"),
        )

    m = re.fullmatch(r"(?:focus|switch\s+to|go\s+to)\s+([a-z0-9 .+-]{2,40})", t)
    if m:
        name = m.group(1).strip()
        if not _is_deixis(name):
            cap = _cap("windows.focus_app", {"name": name}, conf=0.88, source="pattern")
            return _result(cap, _step(cap.tool, {"name": name}, expected_result=f"{name} focused"))

    m = re.fullmatch(r"(?:close|quit|exit)\s+([a-z0-9 .+-]{2,40})", t)
    if m:
        name = m.group(1).strip()
        if name not in ("fullscreen",) and not _is_deixis(name):
            cap = _cap("windows.close_app", {"name": name}, conf=0.85, source="pattern")
            return _result(cap, _step(cap.tool, {"name": name}, expected_result=f"{name} closed"))

    m = re.search(
        r"\bmove\s+(?:(\w+)\s+)?"
        r"(?:to\s+|onto\s+)?"
        r"(?:the\s+|my\s+)?"
        r"(?:"
        r"(?:monitor|screen)\s+"
        r"(\d+|other|another|second|2nd|left|right|main|primary|foreground|current)"
        r"|"
        r"(other|another|second|left|right|main|primary|foreground|current)\s+"
        r"(?:monitor|screen|display)"
        r")\b",
        t,
    )
    if m:
        app = (m.group(1) or "chrome").strip()
        mon_raw = m.group(2) or m.group(3)
        try:
            from neuron.windows.monitors import normalize_monitor_arg
            monitor = normalize_monitor_arg(mon_raw)
        except Exception:
            monitor = mon_raw
        # Keep NL tokens (other/left/…) — never hardcode other→2
        if monitor is None:
            monitor = mon_raw
        cap = _cap(
            "windows.move_to_monitor",
            {"title": app, "monitor": monitor},
            conf=0.85,
            source="pattern",
        )
        return _result(
            cap,
            _step(
                "move_window_to_monitor",
                {"title": app, "monitor": monitor},
                expected_result=f"on monitor {monitor}",
            ),
        )

    # Open <app> on monitor <ref>
    m = re.search(
        r"\bopen\s+([a-z0-9 .+-]{2,40}?)\s+"
        r"(?:on|to|onto)\s+(?:the\s+|my\s+)?"
        r"(?:monitor|screen|display)\s*"
        r"(\d+|other|another|second|2nd|left|right|main|primary|foreground|current)\b",
        t,
    )
    if m and not looks_like_multi:
        app = m.group(1).strip()
        mon_raw = m.group(2)
        try:
            from neuron.windows.monitors import normalize_monitor_arg
            monitor = normalize_monitor_arg(mon_raw) or mon_raw
        except Exception:
            monitor = mon_raw
        if not _is_deixis(app):
            cap = _cap(
                "windows.open_app",
                {"name": app, "monitor": monitor},
                conf=0.88,
                source="pattern",
            )
            return _result(
                cap,
                _step("open_app", {"name": app}, expected_result=f"{app} open"),
                _step(
                    "move_window_to_monitor",
                    {"name": app, "monitor": monitor},
                    expected_result=f"on monitor {monitor}",
                ),
            )

    m = re.fullmatch(r"open\s+([a-z0-9 .+-]{2,40})", t)
    if m:
        name = m.group(1).strip()
        if _is_deixis(name):
            return None
        if name in _WEBSITES or name.replace(" ", "") == "youtube":
            site = "youtube" if name in ("yt", "youtube") else name
            cap = _cap("browser.open", {"site": site}, conf=0.9, source="pattern")
            return _result(cap, _step("open_website", {"site": site}, expected_result=f"{site} open"))
        cap = _cap("windows.open_app", {"name": name}, conf=0.88, source="pattern")
        return _result(cap, _step("open_app", {"name": name}, expected_result=f"{name} open"))

    return None


def _is_deixis(name: str) -> bool:
    return bool(
        re.search(
            r"\b(it|that|this|them|those|these|there|first|second|third|last|one)\b",
            name or "",
            re.I,
        )
    )


def _route_from_intent(intent: Any) -> RouteResult | None:
    if intent is None:
        return None
    kind = getattr(intent, "kind", "") or ""
    action = (getattr(intent, "action", "") or "").strip()
    args = dict(getattr(intent, "args", None) or {})
    if kind not in ("deterministic", "recipe") or not action:
        return None

    tool_to_cap = {
        "skip_ad": "youtube.skip_ad",
        "youtube_skip_ad": "youtube.skip_ad",
        "youtube.skip_ad": "youtube.skip_ad",
        "youtube_home": "youtube.home",
        "open_app": "windows.open_app",
        "focus_app": "windows.focus_app",
        "close_app": "windows.close_app",
        "open_website": "browser.open",
        "search_site": "youtube.search",
        "play_result": "youtube.play_first",
        "run_procedure": "procedure.run",
        "open_folder": "files.open_downloads",
        "type_text": "input.type",
        "press_keys": "input.copy",
        "page_scroll": "ui.scroll",
        "scroll": "ui.scroll",
        "volume": "system.volume",
        "wait": "system.wait",
        "speak": "system.speak",
        "verify": "system.verify",
    }
    cid = tool_to_cap.get(action) or tool_to_cap.get(action.replace(".", "_"))
    if not cid:
        cid = f"tool.{action.replace('.', '_')}"
    conf = float(getattr(intent, "confidence", 0.8) or 0.8)
    if not _registry_has(action):
        return None
    domain = _domain_for_cap(cid)
    method, fallbacks = choose_control_method(domain, browser_context=_browser_context())
    cap = Capability(
        id=cid,
        tool=action,
        args=args,
        confidence=max(conf, 0.8),
        source="intent",
        description=f"from intent:{kind}",
        control_method=method,
        fallback_methods=fallbacks,
    )
    return _result(cap, _step(action, args))


def route(
    raw: str,
    *,
    intent: Any | None = None,
    min_confidence: float = 0.75,
) -> RouteResult:
    raw_l = (raw or "").strip().lower()
    text = ""
    if intent is not None:
        text = (getattr(intent, "normalized", None) or "") or ""
    if not text:
        try:
            import nlu
            u = nlu.understand(raw or "")
            text = u.get("canonical") or u.get("cleaned") or (raw or "")
        except Exception:
            text = raw or ""
    text = (text or "").strip().lower()

    for candidate in (raw_l, text):
        if not candidate:
            continue
        hit = _route_patterns(candidate)
        if hit and hit.ok and hit.capability and hit.capability.confidence >= min_confidence:
            return hit

    hit = _route_from_intent(intent)
    if hit and hit.ok and hit.capability and hit.capability.confidence >= min_confidence:
        return hit

    return RouteResult(ok=False, reason="unsupported")


def list_capabilities() -> list[str]:
    return sorted(_CAPABILITY_TOOLS.keys())
