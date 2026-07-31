"""Blender skill workflows."""

from __future__ import annotations

import time
from pathlib import Path

from neuron.skills._util import arg, as_result, handler
from neuron.skills import files as files_skill
from neuron.skills import windows as win_skill
from neuron.windows.result import ToolResult, fail, ok


def open() -> ToolResult:
    return win_skill.open_app("blender")


def focus() -> ToolResult:
    return win_skill.focus_app("blender")


def open_project(path: str = "", query: str = "") -> ToolResult:
    """Open a .blend file. Pass path, or a search query to find one."""
    p = (path or "").strip()
    q = (query or "").strip()
    if not p and not q:
        return fail("Need a .blend path or project name to find.")

    if not p and q:
        # Prefer *.blend matches
        needle = q if q.lower().endswith(".blend") else f"{q}.blend"
        hit = files_skill.find(needle if "*" not in needle else q, limit=10)
        if not hit.success:
            # Broader search
            hit = files_skill.find(q if ".blend" in q.lower() else f"*{q}*.blend", limit=10)
        if not hit.success:
            return hit
        paths = (
            (hit.state or {}).get("hits")
            or (hit.state or {}).get("paths")
            or (hit.state or {}).get("results")
            or []
        )
        chosen = None
        if isinstance(paths, list):
            for item in paths:
                cand = item.get("path") if isinstance(item, dict) else str(item)
                if cand and str(cand).lower().endswith(".blend"):
                    chosen = cand
                    break
            if not chosen and paths:
                first = paths[0]
                chosen = first.get("path") if isinstance(first, dict) else str(first)
        if not chosen:
            return fail(f"No .blend project found for '{q}'.")
        p = chosen

    path_obj = Path(p)
    if not path_obj.is_file() and not p.lower().endswith(".blend"):
        # Try as name under common folders
        alt = files_skill.find(f"{p}.blend" if not p.lower().endswith(".blend") else p, limit=5)
        if alt.success:
            paths = (alt.state or {}).get("hits") or (alt.state or {}).get("paths") or []
            if paths:
                first = paths[0]
                p = first.get("path") if isinstance(first, dict) else str(first)

    r = files_skill.open(path=p)
    if r.success:
        time.sleep(0.8)
        focus()
        return ok(f"Opened Blender project {Path(p).name}.", state={"path": p}, method="blender")
    # Fallback: launch Blender then hope user picks file
    open()
    return fail(r.message or f"Couldn't open Blender project: {p}")


def new_file() -> ToolResult:
    """Focus Blender and trigger File→New via Ctrl+N (best-effort)."""
    r = open()
    if not r.success:
        return r
    time.sleep(1.0)
    try:
        import actions
        actions.press_keys("control n")
        return ok("Started a new Blender file (Ctrl+N).", method="blender")
    except Exception as exc:
        return fail(str(exc))


def wait_for_app(timeout: float = 12.0) -> ToolResult:
    """Wait until Blender process/window is detectable (semantic, not coordinates)."""
    deadline = time.time() + max(1.0, float(timeout or 12))
    last = None
    while time.time() < deadline:
        last = focus()
        if last.success:
            return ok("Blender is ready.", state={"waited": True}, method="blender")
        time.sleep(0.5)
    return fail(last.message if last else "Blender did not appear in time.")


def trigger_render() -> ToolResult:
    """Start render via F12 (adaptive — no screen coordinates)."""
    r = focus()
    if not r.success:
        r = open()
        if not r.success:
            return r
        time.sleep(1.0)
    try:
        import actions
        actions.press_keys("f12")
        return ok("Triggered Blender render (F12).", method="blender")
    except Exception as exc:
        return fail(str(exc))


def verify_render_started() -> ToolResult:
    """Best-effort check that Blender is still present after render trigger."""
    fr = focus()
    if fr.success:
        return ok("Blender focused after render trigger.", state={"soft": True}, method="blender")
    return fail(fr.message or "Could not verify Blender after render.")


def start_render(project: str = "", path: str = "") -> ToolResult:
    """Semantic skill: open project (optional) → wait → trigger render → verify."""
    proj = (project or path or "").strip()
    if proj:
        r = open_project(path=proj if proj.lower().endswith(".blend") else "", query=proj)
        if not r.success and proj.lower().endswith(".blend"):
            return r
    else:
        r = open()
        if not r.success:
            return r
    w = wait_for_app(8.0)
    if not w.success:
        return w
    tr = trigger_render()
    if not tr.success:
        return tr
    time.sleep(0.8)
    vr = verify_render_started()
    return ok(
        f"Started Blender render{(' for ' + proj) if proj else ''}. {vr.message}",
        state={"project": proj or None, "render": True},
        method="blender",
    )


open_tool = handler(lambda a: open())
focus_tool = handler(lambda a: focus())
open_project_tool = handler(
    lambda a: open_project(
        str(arg(a, "path", "file", "project", default="")),
        str(arg(a, "query", "name", default="")),
    )
)
new_file_tool = handler(lambda a: new_file())
wait_for_app_tool = handler(lambda a: wait_for_app(float(arg(a, "timeout", "seconds", default=12) or 12)))
trigger_render_tool = handler(lambda a: trigger_render())
verify_render_tool = handler(lambda a: verify_render_started())
start_render_tool = handler(
    lambda a: start_render(
        str(arg(a, "project", "query", "name", default="")),
        str(arg(a, "path", "file", default="")),
    )
)
