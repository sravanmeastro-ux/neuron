"""Unified ComputerState — desktop awareness for NEURON AgentLoop.

Composes existing sources (does NOT replace vision_agent):
  world_model → monitors / focused app / cursor
  windows.state → foreground hwnd / title
  snapshot / UIA → accessibility elements
  browser → URL / DOM
  perception pipeline → OCR / screenshot / optional VLM
  vision_agent → spoken/VLM fallback only when requested

Priority for grounding actions:
  Windows UIA / accessibility
  → browser DOM
  → OCR
  → vision model
  → raw coordinate guessing

Answers internally:
  What application am I looking at?
  Which monitor contains Chrome?
  What window currently has focus?
  What clickable UI elements exist?
  Did the UI change after my last action?
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from neuron.uia.types import CLICK_PREFERRED


# Last / previous captured states for change detection across AgentLoop steps
_LAST_STATE: "ComputerState | None" = None
_PREV_STATE: "ComputerState | None" = None


@dataclass
class ComputerState:
    """Single structured view of the live desktop."""

    # Focus / app
    active_application: str = ""
    focused_window_title: str = ""
    focused_hwnd: int = 0
    focused_monitor: int | None = None
    sticky_app: str = ""
    scene: str = ""

    # Monitors + windows
    monitors: list[dict[str, Any]] = field(default_factory=list)
    open_windows: list[dict[str, Any]] = field(default_factory=list)

    # Processes (light)
    processes: list[dict[str, Any]] = field(default_factory=list)

    # UI / a11y
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    clickable_elements: list[dict[str, Any]] = field(default_factory=list)

    # Browser
    browser_url: str = ""
    browser_title: str = ""
    browser_dom_summary: str = ""
    browser_elements: list[dict[str, Any]] = field(default_factory=list)

    # Perception
    visible_text: list[str] = field(default_factory=list)
    ocr_text: list[str] = field(default_factory=list)
    vision_description: str = ""
    screenshot_path: str = ""
    cursor: dict[str, Any] = field(default_factory=dict)

    # Meta
    world_model_text: str = ""
    sources: list[str] = field(default_factory=list)
    fingerprint_value: str = ""
    captured_at: float = 0.0
    error: str | None = None

    # ------------------------------------------------------------------ API
    def looking_at(self) -> str:
        """What application am I looking at?"""
        return (
            self.active_application
            or self.sticky_app
            or _app_from_title(self.focused_window_title)
            or "?"
        )

    def focused_window(self) -> dict[str, Any]:
        """What window currently has focus?"""
        return {
            "title": self.focused_window_title,
            "hwnd": self.focused_hwnd,
            "application": self.looking_at(),
            "monitor": self.focused_monitor,
        }

    def monitor_for_app(self, name: str) -> int | None:
        """Which monitor contains <app>? Returns 1-based monitor id or None."""
        needle = (name or "").strip().lower()
        if not needle:
            return None
        # Prefer open_windows scan (more accurate than primary-app guess)
        for w in self.open_windows:
            title = (w.get("title") or "").lower()
            app = (w.get("app") or "").lower()
            if needle in title or needle in app or _app_matches(needle, app, title):
                mid = w.get("monitor_id")
                if mid is not None:
                    return int(mid)
        for m in self.monitors:
            app = (m.get("app") or "").lower()
            title = (m.get("title") or "").lower()
            details = " ".join(str(d) for d in (m.get("details") or [])).lower()
            if (
                needle in app
                or needle in title
                or needle in details
                or _app_matches(needle, app, title)
            ):
                return int(m.get("monitor") or m.get("id") or 0) or None
        return None

    def clickables(self, *, limit: int = 40) -> list[dict[str, Any]]:
        """What clickable UI elements exist? Prefers UIA, then browser DOM."""
        if self.clickable_elements:
            return list(self.clickable_elements)[:limit]
        out: list[dict[str, Any]] = []
        for e in self.ui_elements:
            if _is_clickable(e):
                out.append(e)
            if len(out) >= limit:
                return out
        for e in self.browser_elements:
            role = (e.get("control_type") or e.get("role") or "").lower()
            if role in ("link", "button", "a", "dom") or e.get("name"):
                out.append({**e, "source": e.get("source") or "browser_dom"})
            if len(out) >= limit:
                break
        return out[:limit]

    def fingerprint(self) -> str:
        """Stable-ish structural fingerprint for change detection."""
        if self.fingerprint_value:
            return self.fingerprint_value
        parts = [
            self.focused_window_title or "",
            str(self.focused_hwnd or ""),
            self.looking_at(),
            self.browser_url or "",
            ",".join(
                sorted(
                    {
                        (e.get("name") or "")[:40]
                        for e in (self.ui_elements or [])[:30]
                        if e.get("name")
                    }
                )
            ),
            ",".join((self.visible_text or [])[:12]),
        ]
        raw = "|".join(parts)
        self.fingerprint_value = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]
        return self.fingerprint_value

    def changed_since(self, previous: "ComputerState | None") -> dict[str, Any]:
        """Did the UI change after my last action?"""
        if previous is None:
            return {
                "changed": True,
                "reason": "no_previous_state",
                "diffs": ["first_observation"],
            }
        diffs: list[str] = []
        if (self.focused_window_title or "") != (previous.focused_window_title or ""):
            diffs.append(
                f"focus_title: {(previous.focused_window_title or '')[:40]!r} -> "
                f"{(self.focused_window_title or '')[:40]!r}"
            )
        if int(self.focused_hwnd or 0) != int(previous.focused_hwnd or 0):
            diffs.append(f"hwnd: {previous.focused_hwnd} -> {self.focused_hwnd}")
        if (self.looking_at() or "").lower() != (previous.looking_at() or "").lower():
            diffs.append(f"app: {previous.looking_at()} -> {self.looking_at()}")
        if (self.browser_url or "") != (previous.browser_url or ""):
            diffs.append(
                f"url: {(previous.browser_url or '')[:60]} -> {(self.browser_url or '')[:60]}"
            )
        prev_names = {(e.get("name") or "").strip().lower() for e in previous.ui_elements if e.get("name")}
        cur_names = {(e.get("name") or "").strip().lower() for e in self.ui_elements if e.get("name")}
        if prev_names or cur_names:
            added = sorted(cur_names - prev_names)[:8]
            removed = sorted(prev_names - cur_names)[:8]
            if added:
                diffs.append("uia_added: " + ", ".join(added))
            if removed:
                diffs.append("uia_removed: " + ", ".join(removed))
        if self.fingerprint() != previous.fingerprint():
            if not diffs:
                diffs.append("fingerprint_changed")
        return {
            "changed": bool(diffs),
            "reason": diffs[0] if diffs else "unchanged",
            "diffs": diffs,
            "before": previous.fingerprint(),
            "after": self.fingerprint(),
        }

    def answer(self, question: str) -> str:
        """Natural-language internal Q&A over this state."""
        q = (question or "").strip().lower()
        if not q:
            return self.looking_at()
        if any(k in q for k in ("looking at", "what application", "what app", "active app", "focused app")):
            return f"Active application: {self.looking_at()}"
        if "which monitor" in q or ("monitor" in q and ("contain" in q or "chrome" in q or "discord" in q)):
            m = re.search(r"(?:contain|contains|has|with)\s+(.+?)(?:\?|$)", q)
            name = (m.group(1) if m else "").strip()
            if not name:
                for cand in ("chrome", "discord", "spotify", "blender", "edge", "firefox", "notepad"):
                    if cand in q:
                        name = cand
                        break
            mid = self.monitor_for_app(name) if name else None
            if mid:
                return f"{name.strip().title()} is on monitor {mid}."
            return f"I couldn't find a monitor for '{name or 'that app'}'."
        if any(k in q for k in ("focus", "focused window", "has focus", "foreground")):
            fw = self.focused_window()
            return (
                f"Focused window: {fw.get('title') or '?'} "
                f"(app={fw.get('application')}, monitor={fw.get('monitor')})."
            )
        if any(k in q for k in ("clickable", "ui element", "buttons", "controls")):
            els = self.clickables(limit=12)
            if not els:
                return "No clickable UI elements detected right now."
            bits = []
            for e in els:
                n = e.get("name") or "?"
                t = (e.get("control_type") or e.get("role") or "").replace("Control", "")
                xy = ""
                if e.get("center_x") is not None and e.get("center_y") is not None:
                    xy = f" @({e['center_x']},{e['center_y']})"
                bits.append(f"{t}:{n}{xy}" if t else f"{n}{xy}")
            return f"{len(els)} clickables: " + "; ".join(bits)
        if any(k in q for k in ("change", "changed", "differ", "after")):
            # Prefer previous-before-last so a fresh capture can still diff
            prev = get_previous_state() or get_last_state()
            if prev is self:
                prev = get_previous_state()
            diff = self.changed_since(prev)
            if not diff.get("changed"):
                return "UI appears unchanged since the last observation."
            return "UI changed: " + "; ".join(diff.get("diffs") or [diff.get("reason") or "yes"])
        if "cursor" in q or "mouse" in q:
            c = self.cursor or {}
            return f"Cursor at {c.get('x')},{c.get('y')} (monitor {c.get('monitor')})."
        if "url" in q or "browser" in q or "page" in q:
            return f"Browser: {self.browser_title or '?'} | {self.browser_url or 'no url'}"
        return self.compact(500)

    def compact(self, max_chars: int = 1600) -> str:
        """Planner / log friendly text (prefers world_model format when present)."""
        if self.world_model_text:
            base = self.world_model_text.strip()
            extra = []
            if self.clickable_elements:
                labels = [
                    (e.get("name") or "")[:40]
                    for e in self.clickable_elements[:10]
                    if e.get("name")
                ]
                if labels:
                    extra.append("Clickables: " + "; ".join(labels))
            if self.browser_url:
                extra.append(f"Browser URL: {self.browser_url[:120]}")
            if self.scene:
                extra.append(f"Scene: {self.scene}")
            text = base + ("\n" + "\n".join(extra) if extra else "")
        else:
            lines = [
                f"Active application: {self.looking_at()}",
                f"Focused window: {self.focused_window_title or '?'}",
                f"Focused monitor: {self.focused_monitor or '?'}",
            ]
            c = self.cursor or {}
            if c.get("x") is not None:
                lines.append(f"Cursor position: {c.get('x')},{c.get('y')}")
            if self.browser_url:
                lines.append(f"Browser: {self.browser_url[:120]}")
            if self.clickables(limit=8):
                lines.append(
                    "Clickables: "
                    + "; ".join((e.get("name") or "?")[:40] for e in self.clickables(limit=8))
                )
            text = "\n".join(lines)
        if self.sources:
            text += "\nSources: " + ",".join(self.sources)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["looking_at"] = self.looking_at()
        d["fingerprint"] = self.fingerprint()
        d["clickables_count"] = len(self.clickables())
        return d

    def to_observe_dict(self) -> dict[str, Any]:
        """Shape compatible with verifier.observe_world consumers."""
        return {
            "app": self.looking_at(),
            "window": self.focused_window_title,
            "hwnd": self.focused_hwnd,
            "url": self.browser_url,
            "scene": self.scene,
            "focused_monitor": self.focused_monitor,
            "active_application": self.looking_at(),
            "cursor": dict(self.cursor or {}),
            "world_model": self.world_model_text,
            "visible_text": list(self.visible_text or [])[:40],
            "ocr_text": list(self.ocr_text or [])[:40],
            "screen_blob": " | ".join(
                list(self.visible_text or [])[:30] + list(self.ocr_text or [])[:20]
            )[:2000],
            "screen_sources": [s for s in self.sources if s in ("uia", "ocr", "browser", "vlm", "dom")],
            "clickables": self.clickables(limit=20),
            "fingerprint": self.fingerprint(),
            "computer_state": True,
        }


# ------------------------------------------------------------------ capture


def capture(
    *,
    deep: bool = False,
    use_ocr: bool = False,
    use_vision: bool = False,
    screenshot: bool = False,
    remember: bool = True,
    request: str = "",
) -> ComputerState:
    """Capture a unified ComputerState from existing NEURON subsystems.

    Cascade: UIA/a11y → browser DOM → OCR → vision (optional) → coords elsewhere.
    """
    state = ComputerState(captured_at=time.time())

    # 1) World model — monitors, active app, cursor (fast, local)
    try:
        from neuron.brain.world_model import build_world_model
        wm = build_world_model(deep=False, use_ocr=False)
        state.world_model_text = wm.get("text") or ""
        state.monitors = list(wm.get("monitors") or [])
        state.active_application = wm.get("active_application") or ""
        state.focused_window_title = wm.get("active_window") or ""
        state.focused_monitor = wm.get("focused_monitor")
        state.cursor = dict(wm.get("cursor") or {})
        br = wm.get("browser") or {}
        if br.get("url"):
            state.browser_url = str(br.get("url") or "")[:400]
        state.sources.append("world_model")
    except Exception as exc:
        state.error = f"world_model: {exc}"

    # 2) Authoritative foreground hwnd/title
    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        if fg.get("title"):
            state.focused_window_title = (fg.get("title") or "")[:160]
        state.focused_hwnd = int(fg.get("hwnd") or 0)
        if not state.active_application and state.focused_window_title:
            state.active_application = _app_from_title(state.focused_window_title)
        state.sources.append("foreground")
    except Exception:
        pass

    # 3) Open windows list (all monitors)
    try:
        import screen_capture as sc
        wins = sc.list_visible_windows(50) or []
        state.open_windows = [
            {
                "title": (w.get("title") or "")[:120],
                "monitor_id": int(w.get("monitor_id") or 0),
                "hwnd": int(w.get("hwnd") or 0),
                "left": w.get("left"),
                "top": w.get("top"),
                "width": w.get("width"),
                "height": w.get("height"),
                "app": _app_from_title(w.get("title") or ""),
            }
            for w in wins
        ]
        state.sources.append("windows")
    except Exception:
        pass

    # 4) Light process info for running apps of interest
    try:
        state.processes = _running_apps_light()
        if state.processes:
            state.sources.append("processes")
    except Exception:
        pass

    # 5) Context snapshot — scene + sticky + light/deep UIA/browser
    snap = None
    try:
        from neuron.brain.snapshot import gather_snapshot
        snap = gather_snapshot(request, deep=deep)
        if snap.sticky_app:
            state.sticky_app = snap.sticky_app
        if snap.scene:
            state.scene = snap.scene
        if snap.browser_url and not state.browser_url:
            state.browser_url = snap.browser_url
        if snap.browser_title:
            state.browser_title = snap.browser_title
        if snap.browser_dom_summary:
            state.browser_dom_summary = snap.browser_dom_summary
        if snap.active_application and not state.active_application:
            state.active_application = snap.active_application
        if snap.active_window and not state.focused_window_title:
            state.focused_window_title = snap.active_window
        if snap.monitor and state.focused_monitor is None:
            state.focused_monitor = snap.monitor
        if snap.visible_text:
            state.visible_text = list(snap.visible_text)[:40]
        state.sources.extend([s for s in (snap.sources or []) if s not in state.sources])
    except Exception:
        snap = None

    # 6) Rich UIA clickables — deep path only (light path uses snapshot UIA)
    try:
        if deep:
            state.ui_elements, state.clickable_elements = _gather_uia_clickables(
                deep=True, limit=80
            )
            if state.ui_elements:
                state.sources.append("uia")
        elif snap is not None and snap.ui_elements:
            state.ui_elements = [
                {
                    "name": e.get("name") or "",
                    "control_type": e.get("control_type") or "",
                    "automation_id": e.get("automation_id") or "",
                    "value": e.get("value") or "",
                    "source": "uia",
                }
                for e in snap.ui_elements
            ]
            state.clickable_elements = [e for e in state.ui_elements if _is_clickable(e)]
        for e in state.ui_elements[:24]:
            n = (e.get("name") or "").strip()
            if n and n not in state.visible_text:
                state.visible_text.append(n)
    except Exception:
        pass

    # 7) Browser DOM elements when deep or browser-ish
    want_browser = deep or bool(state.browser_url) or any(
        x in (state.active_application + " " + state.focused_window_title).lower()
        for x in ("chrome", "edge", "firefox", "brave", "youtube", "opera")
    )
    if want_browser:
        try:
            _fill_browser(state, deep=deep)
        except Exception:
            pass

    # 8) OCR fallback (local RapidOCR) when requested or UIA sparse
    uia_sparse = len(state.ui_elements) < 4 and len(state.visible_text) < 4
    if use_ocr or (deep and uia_sparse):
        try:
            from neuron.perception.ocr import ocr_image
            args: dict[str, Any] = {}
            if state.focused_monitor:
                args["monitor"] = state.focused_monitor
            r = ocr_image(args)
            if getattr(r, "success", False):
                st = getattr(r, "state", None) or {}
                texts = list(st.get("visible_text") or st.get("text") or [])[:40]
                state.ocr_text = [str(t) for t in texts if t]
                for t in state.ocr_text:
                    if t not in state.visible_text:
                        state.visible_text.append(t)
                state.sources.append("ocr")
        except Exception:
            pass

    # 9) Screenshot + optional ScreenContext / VLM (heavy — only when asked)
    if screenshot or use_vision:
        try:
            from neuron.perception.pipeline import build_screen_context
            ctx = build_screen_context(
                request=request or "",
                monitor=int(state.focused_monitor) if state.focused_monitor else None,
                use_ocr=use_ocr or use_vision,
                use_vlm=True if use_vision else False,
                force_vlm=bool(use_vision),
            )
            if ctx.screenshot_path:
                state.screenshot_path = ctx.screenshot_path
            if ctx.vision_description:
                state.vision_description = ctx.vision_description
                state.sources.append("vlm")
            if ctx.cursor and not state.cursor:
                state.cursor = dict(ctx.cursor)
            for t in (ctx.visible_text or [])[:20]:
                if t and t not in state.visible_text:
                    state.visible_text.append(t)
            for s in ctx.sources or []:
                if s not in state.sources:
                    state.sources.append(s)
        except Exception:
            # vision_agent fallback for description only — do not replace pipeline
            if use_vision:
                try:
                    import vision_agent
                    if vision_agent.is_enabled():
                        state.vision_description = vision_agent.answer_screen(
                            request or "what is on screen"
                        )[:500]
                        state.sources.append("vision_agent")
                except Exception:
                    pass

    state.fingerprint()  # populate fingerprint_value
    if remember:
        set_last_state(state)
    return state


def get_last_state() -> ComputerState | None:
    return _LAST_STATE


def get_previous_state() -> ComputerState | None:
    return _PREV_STATE


def set_last_state(state: ComputerState | None) -> None:
    global _LAST_STATE, _PREV_STATE
    if state is not None and _LAST_STATE is not None and state is not _LAST_STATE:
        _PREV_STATE = _LAST_STATE
    _LAST_STATE = state


def ui_changed_since_last(current: ComputerState | None = None) -> dict[str, Any]:
    """Compare current (or fresh light capture) against remembered previous state."""
    cur = current or capture(deep=False, remember=False)
    baseline = get_last_state()
    # If current was just remembered as last, compare against previous
    if baseline is cur:
        baseline = get_previous_state()
    return cur.changed_since(baseline)


# ------------------------------------------------------------------ helpers


def _app_from_title(title: str) -> str:
    try:
        from neuron.brain.world_model import _app_from_title as _af
        return _af(title)
    except Exception:
        t = (title or "").strip()
        if " - " in t:
            return t.rsplit(" - ", 1)[-1].strip()[:40]
        return t[:40]


def _app_matches(needle: str, app: str, title: str) -> bool:
    aliases = {
        "chrome": ("chrome", "google chrome", "chromium"),
        "edge": ("edge", "msedge", "microsoft edge"),
        "discord": ("discord",),
        "spotify": ("spotify",),
        "blender": ("blender",),
        "firefox": ("firefox", "mozilla"),
        "code": ("code", "vs code", "vscode", "cursor"),
    }
    for key, names in aliases.items():
        if needle == key or needle in names:
            return any(n in app or n in title for n in names)
    return False


def _is_clickable(el: dict[str, Any]) -> bool:
    ctype = (el.get("control_type") or el.get("role") or "").strip()
    if ctype in CLICK_PREFERRED:
        return bool(el.get("name") or el.get("automation_id"))
    if ctype.endswith("ButtonControl") or ctype in (
        "HyperlinkControl", "MenuItemControl", "TabItemControl", "ListItemControl"
    ):
        return True
    # Named interactive-looking elements
    name = (el.get("name") or "").strip()
    if name and el.get("enabled", True) and not el.get("offscreen"):
        if ctype in ("EditControl",):
            return False
        if ctype in CLICK_PREFERRED or "Button" in ctype or "Item" in ctype:
            return True
    return False


def _gather_uia_clickables(*, deep: bool, limit: int) -> tuple[list[dict], list[dict]]:
    from neuron.uia import inspect as uia_inspect
    from neuron.uia.types import CLICK_PREFERRED as PREF

    _win, elements = uia_inspect.walk_elements(
        max_depth=5 if deep else 3,
        max_elements=limit,
        named_only=False,
        interesting_only=True,
        time_budget=2.5 if deep else 1.5,
    )
    ui: list[dict[str, Any]] = []
    click: list[dict[str, Any]] = []
    for e in elements or []:
        d = e.to_dict() if hasattr(e, "to_dict") else dict(e)
        d["source"] = "uia"
        ui.append({
            "name": d.get("name") or "",
            "control_type": d.get("control_type") or "",
            "automation_id": d.get("automation_id") or "",
            "value": d.get("value") or "",
            "center_x": d.get("center_x"),
            "center_y": d.get("center_y"),
            "left": d.get("left"),
            "top": d.get("top"),
            "width": d.get("width"),
            "height": d.get("height"),
            "enabled": d.get("enabled", True),
            "offscreen": d.get("offscreen", False),
            "source": "uia",
        })
        if (d.get("control_type") in PREF or _is_clickable(d)) and (d.get("name") or d.get("automation_id")):
            if d.get("offscreen"):
                continue
            if d.get("enabled") is False:
                continue
            click.append(ui[-1])
    return ui[:limit], click[:limit]


def _fill_browser(state: ComputerState, *, deep: bool) -> None:
    try:
        from neuron.browser import agent as br_agent
    except Exception:
        # Legacy browser module
        try:
            import browser
            if not state.browser_url:
                state.browser_url = (browser.current_url() or "")[:400]
            if state.browser_url:
                state.sources.append("browser")
        except Exception:
            pass
        return

    if not state.browser_url:
        page = br_agent.browser_get_page({})
        if page.success and page.state:
            state.browser_url = (page.state.get("url") or "")[:400]
            state.browser_title = (page.state.get("title") or "")[:160]
            state.sources.append("browser")
    if deep:
        els_r = br_agent.browser_get_elements({"limit": 40})
        if els_r.success and els_r.state:
            for e in (els_r.state.get("elements") or [])[:30]:
                name = (e.get("name") or e.get("text") or "").strip()
                if not name:
                    continue
                item = {
                    "name": name,
                    "control_type": e.get("role") or e.get("tag") or "dom",
                    "automation_id": e.get("id") or "",
                    "value": e.get("href") or "",
                    "center_x": e.get("center_x") or e.get("x"),
                    "center_y": e.get("center_y") or e.get("y"),
                    "source": "browser_dom",
                }
                state.browser_elements.append(item)
                if _is_clickable(item) or item["control_type"] in ("link", "button", "a"):
                    state.clickable_elements.append(item)
            state.sources.append("browser_dom")


def _running_apps_light() -> list[dict[str, Any]]:
    """Small set of known apps currently running (psutil if available)."""
    interesting = {
        "chrome.exe": "Chrome",
        "msedge.exe": "Edge",
        "firefox.exe": "Firefox",
        "Discord.exe": "Discord",
        "Spotify.exe": "Spotify",
        "blender.exe": "Blender",
        "Code.exe": "VS Code",
        "Cursor.exe": "Cursor",
        "steam.exe": "Steam",
        "notepad.exe": "Notepad",
        "explorer.exe": "Explorer",
        "opera.exe": "Opera",
    }
    out: list[dict[str, Any]] = []
    try:
        import psutil
        seen = set()
        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "")
            if name in interesting and name not in seen:
                seen.add(name)
                out.append({"process": name, "app": interesting[name], "running": True})
    except Exception:
        pass
    return out
