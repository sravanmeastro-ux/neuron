"""Goal extraction from natural-language workflow requests."""

from __future__ import annotations

import re

from neuron.taskplan.types import GoalSpec

_APP_PAT = re.compile(
    r"\b(?:open|launch|start|download|install)\s+"
    r"(chrome|google chrome|edge|firefox|blender|notepad|spotify|discord|"
    r"visual studio code|vs\s*code|code|whatsapp(?:\s+web)?|"
    r"cursor|steam)\b",
    re.I,
)

_DESTRUCTIVE = re.compile(
    r"\b(delete|remove|uninstall|format|wipe|overwrite|move\s+all|"
    r"zip|install|download\s+and\s+install)\b",
    re.I,
)


def extract_goal(text: str) -> GoalSpec:
    raw = (text or "").strip()
    apps: list[str] = []
    for m in _APP_PAT.finditer(raw):
        name = re.sub(r"\s+", " ", m.group(1).strip().lower())
        canon = {
            "google chrome": "Chrome",
            "chrome": "Chrome",
            "visual studio code": "Code",
            "vs code": "Code",
            "vscode": "Code",
            "code": "Code",
            "whatsapp web": "WhatsApp",
            "whatsapp": "WhatsApp",
            "blender": "Blender",
            "edge": "Edge",
            "firefox": "Firefox",
            "notepad": "Notepad",
            "spotify": "Spotify",
            "discord": "Discord",
            "cursor": "Cursor",
            "steam": "Steam",
        }.get(name, name.title())
        if canon not in apps:
            apps.append(canon)

    summary = re.split(r"[.!?]", raw)[0].strip()[:120] or raw[:120]
    criteria: list[str] = []
    low = raw.lower()
    if "play" in low:
        criteria.append("media or result is playing / opened")
    if "install" in low:
        criteria.append("installer launched or install confirmed")
    if "zip" in low:
        criteria.append("zip archive exists")
    if "hello world" in low:
        criteria.append("hello world file created and run attempted")
    if "archive" in low and "chat" in low:
        criteria.append("chat archived")
    if not criteria:
        criteria.append("all planned subtasks completed")

    return GoalSpec(
        text=raw,
        summary=summary,
        applications=apps,
        completion_criteria=criteria,
        destructive=bool(_DESTRUCTIVE.search(raw)),
        source="voice",
    )
