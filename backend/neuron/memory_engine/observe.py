"""Observe hooks — feed LTM from tools / utterances without rewriting cores."""

from __future__ import annotations

import re
from typing import Any


def observe_tool(name: str, args: dict | None = None, *, ok: bool = True) -> None:
    try:
        from neuron.memory_engine.engine import enabled, note_desktop, note_project, append_episode
        if not enabled() or not ok:
            return
    except Exception:
        return
    args = args or {}
    tool = (name or "").strip()

    if tool in ("open_app", "focus_app"):
        app = str(args.get("name") or args.get("application") or "")
        if app:
            note_desktop(app=app)
            append_episode(f"Opened {app}", meta={"tool": tool, "app": app})

    if tool in ("open_folder", "open_file"):
        folder = str(args.get("location") or args.get("path") or args.get("folder") or args.get("name") or "")
        if folder:
            note_desktop(folder=folder)
            append_episode(f"Used folder/file {folder}", meta={"tool": tool, "folder": folder})

    if tool in ("open_website", "browser_navigate", "browser_search"):
        site = str(args.get("url") or args.get("site") or args.get("query") or "")[:120]
        if site:
            append_episode(f"Visited {site}", meta={"tool": tool, "site": site})

    # Heuristic project from path / folder name
    for key in ("path", "location", "folder", "name"):
        val = str(args.get(key) or "")
        m = re.search(r"(?:\\|/)(Projects|repos|workspace|code)(?:\\|/)?([^\\/]+)?", val, re.I)
        if m:
            proj = m.group(2) or m.group(1)
            note_project(proj, detail=f"Active path {val[:160]}")
            break


def observe_utterance(text: str, *, acted: bool = True) -> None:
    if not acted or not (text or "").strip():
        return
    try:
        from neuron.memory_engine.engine import enabled, append_conversation, append_episode, note_project
        if not enabled():
            return
    except Exception:
        return
    append_conversation("user", text)
    low = text.lower()
    if re.search(r"\b(project|working on|repo)\b", low):
        m = re.search(r"(?:project|working on|repo)\s+([A-Za-z0-9_.-]+)", text, re.I)
        if m:
            note_project(m.group(1), detail=text[:200])
        else:
            append_episode(text[:200], meta={"utterance": True})
    elif len(text) > 12:
        append_episode(f"Command: {text[:180]}", meta={"utterance": True})
