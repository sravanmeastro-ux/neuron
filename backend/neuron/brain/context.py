"""Gather live context for the planner (includes Phase 8 ContextSnapshot)."""

from __future__ import annotations

from neuron.brain.snapshot import ContextSnapshot, gather_snapshot


def gather(request: str = "", *, snapshot: ContextSnapshot | None = None) -> str:
    chunks: list[str] = []
    try:
        import memory
        blob = memory.context_blob(request)
        if blob:
            chunks.append(blob)
    except Exception:
        pass

    try:
        import app_context
        app = ""
        if hasattr(app_context, "get_app"):
            app = app_context.get_app() or ""
        if not app and hasattr(app_context, "current_app"):
            app = app_context.current_app() or ""
        if app:
            chunks.append(f"FOREGROUND_APP_HINT: {app}")
    except Exception:
        pass

    try:
        import monitor_focus
        mid = monitor_focus.get_focus()
        if mid:
            chunks.append(f"STICKY_MONITOR: {mid}")
    except Exception:
        pass

    try:
        from neuron.tools import windows as win_t
        mons = win_t.get_monitors({})
        if mons:
            chunks.append(f"MONITORS: {mons}")
    except Exception:
        pass

    # Phase 8 structured snapshot (preferred over ad-hoc screen dumps)
    try:
        snap = snapshot if snapshot is not None else gather_snapshot(request, deep=False)
        compact = snap.compact(1100)
        if compact:
            chunks.append("CONTEXT_SNAPSHOT:\n" + compact)
    except Exception:
        snap = None

    # Phase 5 ScreenContext (heavy OCR/VLM only for screen-related asks)
    try:
        from neuron.perception.pipeline import build_screen_context
        want_heavy = bool(request and any(
            w in request.lower()
            for w in (
                "screen", "monitor", "describe", "look", "see",
                "what is on", "what's on", "how many", "ocr", "click that",
            )
        ))
        if want_heavy:
            ctx = build_screen_context(
                request=request or "",
                use_ocr=True,
                use_vlm=True,
                force_vlm=False,
            )
            compact = ctx.compact(900)
            if compact:
                chunks.append("SCREEN_CONTEXT:\n" + compact)
    except Exception:
        if snap is None or not snap.ui_elements:
            try:
                from neuron.tools import uia_tools
                tree = uia_tools.get_ui_tree({"depth": 3, "limit": 28})
                blob = str(tree) if tree is not None else ""
                if blob:
                    chunks.append("UI_SNIPPET:\n" + blob[:900])
            except Exception:
                pass

    try:
        import voice_recipes
        recipes = voice_recipes.for_prompt(12)
        if recipes:
            chunks.append(recipes[:700])
    except Exception:
        pass

    try:
        from neuron.memory.store import recent_tool_runs
        runs = recent_tool_runs(6)
        if runs:
            chunks.append("RECENT_TOOL_RUNS:\n" + "\n".join(runs))
    except Exception:
        pass

    text = "\n\n".join(c for c in chunks if c)
    if len(text) > 3800:
        text = text[-3800:]
    return text


def gather_with_snapshot(request: str = "", *, deep: bool = False) -> tuple[str, ContextSnapshot]:
    snap = gather_snapshot(request, deep=deep)
    return gather(request, snapshot=snap), snap
