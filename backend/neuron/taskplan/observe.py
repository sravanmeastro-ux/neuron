"""Lightweight observe — reuse world model / screen memory (no rewrites)."""

from __future__ import annotations

from neuron.taskplan.types import Observation


def observe() -> Observation:
    app = ""
    title = ""
    notes = ""
    raw: dict = {}
    try:
        from neuron.brain.world_model import build_world_model
        wm = build_world_model(deep=False, use_ocr=False) or {}
        raw["world"] = {k: wm.get(k) for k in ("active_app", "active_window", "monitors") if k in wm}
        app = str(wm.get("active_app") or wm.get("foreground_app") or "")
        title = str(wm.get("active_window") or wm.get("foreground_title") or "")
    except Exception:
        pass
    try:
        from neuron.screen import screen_context
        mem = screen_context.summary()
        raw["screen"] = mem
        app = app or str(mem.get("application") or "")
        title = title or str(mem.get("current_window") or "")
        if mem.get("button_count"):
            notes = f"{mem.get('button_count')} buttons remembered"
    except Exception:
        pass
    if not app and not title:
        try:
            import actions
            # get_active_window may exist via tools; soft fail
            pass
        except Exception:
            pass
    return Observation(application=app, window_title=title, notes=notes, raw=raw)
