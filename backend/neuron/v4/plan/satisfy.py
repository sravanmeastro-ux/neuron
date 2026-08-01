"""Already-satisfied / precondition evaluation against DesktopWorldModel.

UNKNOWN is never treated as satisfied.
"""

from __future__ import annotations

from typing import Any

from neuron.v4.plan.types import StepStatus, Subgoal
from neuron.v4.world.models import DesktopState, KnowledgeLevel


def _app_window(world, app: str):
    if world is None or not app:
        return None
    try:
        return world.get_window_by_application(app)
    except Exception:
        return None


def _desktop(world) -> DesktopState | None:
    if world is None:
        return None
    cur = getattr(world, "current", None)
    return cur if isinstance(cur, DesktopState) else None


def knowledge_ok(level: KnowledgeLevel | str | None) -> bool:
    if level is None:
        return False
    if isinstance(level, KnowledgeLevel):
        return level is KnowledgeLevel.KNOWN
    return str(level).lower() == "known"


def app_open_known(world, app: str) -> bool | None:
    """True=open, False=known-closed/absent with evidence, None=UNKNOWN."""
    desktop = _desktop(world)
    if desktop is None:
        return None
    if not desktop.windows and desktop.knowledge is KnowledgeLevel.UNKNOWN:
        return None
    w = _app_window(world, app)
    if w is not None:
        return True
    # Have window enum but no match → known not open (only if we actually enumerated)
    if desktop.windows or desktop.applications:
        return False
    return None


def app_focused_known(world, app: str) -> bool | None:
    w = _app_window(world, app)
    if w is None:
        open_k = app_open_known(world, app)
        if open_k is False:
            return False
        return None
    if w.focused:
        return True
    active = ""
    try:
        active = (world.get_active_application() or "").lower()
    except Exception:
        pass
    if app.lower() in active or active in app.lower():
        return True
    # Window exists but not focused — known false
    return False


def window_on_monitor_known(world, app: str, monitor: Any) -> bool | None:
    w = _app_window(world, app)
    if w is None:
        return None
    if w.monitor_id is None and w.knowledge is KnowledgeLevel.UNKNOWN:
        return None
    try:
        mon = world.resolve_monitor_reference(monitor, relative_to=w.monitor_id, application=app)
    except Exception:
        mon = None
    if mon is None:
        # Try numeric
        try:
            mid = int(monitor)
            mon = world.get_monitor_by_id(mid)
        except (TypeError, ValueError):
            return None
    if mon is None:
        return None
    if w.monitor_id is not None and int(w.monitor_id) == int(mon.id):
        return True
    # Have placement knowledge and mismatch
    if w.monitor_id is not None:
        return False
    placed = world.get_monitor_for_window(w)
    if placed is None:
        return None
    return int(placed.id) == int(mon.id)


def youtube_loaded_known(world) -> bool | None:
    desktop = _desktop(world)
    if desktop is None:
        return None
    br = desktop.browser
    if br is None:
        # Check chrome title
        w = _app_window(world, "Chrome") or _app_window(world, "Edge")
        if w and "youtube" in (w.title or "").lower():
            return True
        if w is None and not desktop.windows:
            return None
        return False
    url = (br.url or "").lower()
    title = (br.tab_title or "").lower()
    if "youtube.com" in url or "youtu.be" in url or "youtube" in title:
        return True
    if url or title:
        return False
    return None


def subgoal_satisfied(sg: Subgoal, world) -> bool | None:
    """
    Return True if known-satisfied, False if known-unsatisfied, None if UNKNOWN.
    """
    intent = (sg.intent or "").strip().lower()
    hints = sg.target_hints or {}
    app = str(hints.get("name") or hints.get("app") or "").strip()
    mon = hints.get("monitor")

    if intent in ("open_app", "ensure_app"):
        return app_open_known(world, app) if app else None

    if intent in ("focus_app",):
        return app_focused_known(world, app) if app else None

    if intent in ("move_monitor", "place_monitor"):
        if not app or mon is None:
            return None
        return window_on_monitor_known(world, app, mon)

    if intent in ("youtube_home", "ensure_youtube"):
        return youtube_loaded_known(world)

    if intent in ("open_website",) and "youtube" in str(hints.get("url") or hints.get("site") or "").lower():
        return youtube_loaded_known(world)

    # Search / play / fullscreen / click — never skip from empty evidence
    if intent in (
        "youtube_search", "youtube_play", "youtube_fullscreen",
        "browser_search", "click", "type", "press", "resolve",
    ):
        # Optional: if meta says already done this session
        if hints.get("_satisfied") is True:
            return True
        return False  # known need action unless marked — treat as not satisfied

    # Generic completion criteria tags
    for crit in sg.completion_criteria:
        c = (crit or "").lower()
        if "unknown" in c:
            return None
        if app and "window exists" in c:
            return app_open_known(world, app)
        if app and mon is not None and "monitor" in c:
            return window_on_monitor_known(world, app, mon)

    return None


def dependencies_met(sg: Subgoal, plan_subgoals: list[Subgoal]) -> bool:
    if not sg.depends_on:
        return True
    by_id = {s.subgoal_id: s for s in plan_subgoals}
    for dep in sg.depends_on:
        other = by_id.get(dep)
        if other is None:
            return False
        if other.status not in (StepStatus.SUCCEEDED, StepStatus.SKIPPED):
            return False
    return True


__all__ = [
    "app_open_known",
    "app_focused_known",
    "window_on_monitor_known",
    "youtube_loaded_known",
    "subgoal_satisfied",
    "dependencies_met",
    "knowledge_ok",
]
