"""Phase 8 — ContextSnapshot: what the user is currently doing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ContextSnapshot:
    """Unified computer + conversation state for ambiguous command resolution."""

    active_application: str = ""
    active_window: str = ""
    monitor: int | None = None
    browser_url: str = ""
    browser_title: str = ""
    browser_dom_summary: str = ""
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    visible_text: list[str] = field(default_factory=list)
    recent_actions: list[str] = field(default_factory=list)
    recent_conversation: list[dict[str, str]] = field(default_factory=list)
    sticky_app: str = ""
    scene: str = ""  # youtube | explorer | spotify | browser | desktop | unknown
    sources: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compact(self, max_chars: int = 1600) -> str:
        lines = [
            f"app={self.active_application or self.sticky_app or '?'}",
            f"window={self.active_window or '?'}",
            f"scene={self.scene or 'unknown'}",
        ]
        if self.monitor is not None:
            lines.append(f"monitor={self.monitor}")
        if self.browser_url or self.browser_title:
            lines.append(
                f"browser={self.browser_title or '?'} | {self.browser_url or ''}"
            )
        if self.browser_dom_summary:
            lines.append("dom=" + self.browser_dom_summary[:400])
        if self.ui_elements:
            labels = []
            for e in self.ui_elements[:20]:
                n = (e.get("name") or e.get("text") or "").strip()
                t = (e.get("control_type") or e.get("role") or "").strip()
                if n:
                    labels.append(f"{t}:{n}" if t else n)
            if labels:
                lines.append("ui=[" + "; ".join(labels)[:700] + "]")
        if self.visible_text:
            lines.append("text=[" + " | ".join(self.visible_text[:18])[:450] + "]")
        if self.recent_actions:
            lines.append("actions=[" + " | ".join(self.recent_actions[:5])[:280] + "]")
        if self.recent_conversation:
            bits = [
                f"{h.get('role', '?')}:{(h.get('text') or '')[:60]}"
                for h in self.recent_conversation[-4:]
            ]
            lines.append("chat=[" + " | ".join(bits)[:280] + "]")
        if self.sources:
            lines.append("sources=" + ",".join(self.sources))
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def __str__(self) -> str:
        return self.compact()


def infer_scene(snapshot: ContextSnapshot) -> str:
    hay = " ".join(
        [
            snapshot.active_application or "",
            snapshot.active_window or "",
            snapshot.browser_url or "",
            snapshot.browser_title or "",
            snapshot.sticky_app or "",
        ]
    ).lower()
    if "youtube" in hay or "youtu.be" in hay:
        return "youtube"
    if "spotify" in hay:
        return "spotify"
    if any(
        x in hay
        for x in (
            "file explorer",
            "explorer",
            "downloads",
            "documents",
            "this pc",
            "quick access",
        )
    ):
        return "explorer"
    if any(x in hay for x in ("chrome", "edge", "firefox", "brave", "http://", "https://")):
        return "browser"
    if snapshot.browser_url:
        return "browser"
    if snapshot.active_application or snapshot.active_window:
        return "desktop"
    return "unknown"


def gather_snapshot(request: str = "", *, deep: bool = False) -> ContextSnapshot:
    """Collect a ContextSnapshot. deep=True pulls browser DOM + richer UIA."""
    snap = ContextSnapshot()

    try:
        import app_context
        sticky = ""
        if hasattr(app_context, "get_app"):
            sticky = app_context.get_app() or ""
        elif hasattr(app_context, "current_app"):
            sticky = app_context.current_app() or ""
        snap.sticky_app = sticky
        if sticky:
            snap.sources.append("sticky_app")
    except Exception:
        pass

    try:
        import monitor_focus
        mid = monitor_focus.get_focus()
        if mid:
            snap.monitor = int(mid)
            snap.sources.append("monitor")
    except Exception:
        pass

    # Always attach live monitor layout (Phase 10)
    try:
        from neuron.windows import monitors as mon_mod
        mons = mon_mod.list_monitor_dicts()
        if mons and snap.monitor is None:
            snap.monitor = mon_mod.foreground_monitor_id(mons) or int(mons[0]["id"])
        # Stash compact layout into visible_text header via sources note
        if mons:
            snap.sources.append(f"monitors:{len(mons)}")
    except Exception:
        pass

    try:
        from neuron.windows import state as win_state
        fg = win_state.get_foreground() or {}
        title = (fg.get("title") or "").strip()
        if title:
            snap.active_window = title
            snap.sources.append("foreground")
        # Heuristic app name from title (before " - ")
        if title:
            if " - " in title:
                snap.active_application = title.rsplit(" - ", 1)[-1].strip() or title
            else:
                snap.active_application = title.split("—")[0].strip()[:80]
        if snap.sticky_app and not snap.active_application:
            snap.active_application = snap.sticky_app
    except Exception as exc:
        snap.error = str(exc)

    # Light UIA
    try:
        from neuron.uia import actions as uia_actions
        limit = 50 if deep else 28
        depth = 5 if deep else 3
        r = uia_actions.get_ui_tree({"depth": depth, "limit": limit})
        if r.success and r.state:
            win = r.state.get("window") or {}
            if win.get("name") and not snap.active_window:
                snap.active_window = win.get("name") or ""
            els = r.state.get("elements") or []
            snap.ui_elements = [
                {
                    "name": e.get("name") or e.get("text") or "",
                    "control_type": e.get("control_type") or e.get("role") or "",
                    "automation_id": e.get("automation_id") or "",
                    "value": e.get("value") or "",
                }
                for e in els
                if (e.get("name") or e.get("text"))
            ][:limit]
            texts = [
                (e.get("name") or e.get("text") or "").strip()
                for e in els
                if (e.get("name") or e.get("text"))
            ]
            snap.visible_text = [t for t in texts if t][:24]
            snap.sources.append("uia")
    except Exception:
        pass

    # Browser URL / DOM when Chrome/browser-ish or deep
    want_browser = deep or any(
        x in (snap.active_window + " " + snap.active_application).lower()
        for x in ("chrome", "edge", "firefox", "brave", "youtube", "http")
    )
    if want_browser:
        try:
            from neuron.browser import agent as br_agent
            page = br_agent.browser_get_page({})
            if page.success and page.state:
                snap.browser_url = (page.state.get("url") or "")[:400]
                snap.browser_title = (page.state.get("title") or "")[:160]
                text = (page.state.get("text") or "").strip()
                links = page.state.get("links") or []
                bits = []
                if text:
                    bits.append(text[:220])
                for i, L in enumerate(links[:8]):
                    t = (L.get("title") or L.get("text") or "").strip()
                    if t:
                        bits.append(f"[{i}] {t[:80]}")
                snap.browser_dom_summary = " | ".join(bits)[:500]
                # Prefer page text tokens as visible
                if text:
                    extra = [ln.strip() for ln in text.splitlines() if ln.strip()][:12]
                    for x in extra:
                        if x not in snap.visible_text:
                            snap.visible_text.append(x)
                snap.sources.append("browser")
            if deep:
                els_r = br_agent.browser_get_elements({"limit": 40})
                if els_r.success and els_r.state:
                    for e in (els_r.state.get("elements") or [])[:30]:
                        name = (e.get("name") or e.get("text") or "").strip()
                        if not name:
                            continue
                        snap.ui_elements.append(
                            {
                                "name": name,
                                "control_type": e.get("role") or e.get("tag") or "dom",
                                "automation_id": e.get("id") or "",
                                "value": e.get("href") or "",
                            }
                        )
                    snap.sources.append("browser_dom")
        except Exception:
            pass

    # Recent actions
    try:
        from neuron.memory.store import recent_tool_runs
        runs = recent_tool_runs(6)
        snap.recent_actions = [str(x) for x in (runs or [])][:6]
        if snap.recent_actions:
            snap.sources.append("tool_runs")
    except Exception:
        pass

    # Recent conversation
    try:
        import memory
        data = memory._load()
        hist = data.get("history") or []
        snap.recent_conversation = [
            {"role": str(h.get("role") or ""), "text": str(h.get("text") or "")[:200]}
            for h in hist[-6:]
        ]
        if snap.recent_conversation:
            snap.sources.append("conversation")
    except Exception:
        pass

    snap.scene = infer_scene(snap)
    return snap


def enrich_snapshot(snapshot: ContextSnapshot | None = None, request: str = "") -> ContextSnapshot:
    """Medium-confidence path: gather deeper UI + browser DOM."""
    return gather_snapshot(request, deep=True)
