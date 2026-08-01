"""Scenario recipes → CUAction lists or TaskGraph delegation."""

from __future__ import annotations

import re
import time
from typing import Any

from neuron.computer_use.types import CUAction


def _act(kind: str, description: str, args: dict | None = None, *, expected: str = "", confirm: bool = False) -> CUAction:
    return CUAction(
        kind=kind,
        args=dict(args or {}),
        description=description,
        expected=expected or description,
        requires_confirm=confirm,
    )


def plan_actions(text: str) -> tuple[list[CUAction], str, float]:
    """
    Return (actions, source, planner_ms).
    source may be scenario:* or vision_fallback or taskplan_delegate.
    """
    t0 = time.perf_counter()
    raw = (text or "").strip()
    low = raw.lower()

    # Prefer Task Planning for known multi-step templates (do not rewrite taskplan)
    try:
        from neuron.taskplan.decompose import try_templates
        from neuron.taskplan.extract import extract_goal
        g = try_templates(raw, extract_goal(raw))
        if g and g.subtasks:
            # Signal caller to run via taskplan
            return [], "taskplan_delegate", round((time.perf_counter() - t0) * 1000, 2)
    except Exception:
        pass

    actions: list[CUAction] | None = None
    source = "scenario"

    if re.search(r"\bbook\b.+\b(train|ticket|flight)\b|\btrain\s+ticket\b", low):
        actions = _train_ticket(raw)
        source = "scenario:train_ticket"
    elif re.search(r"\bdownload\b.+\bblender\b|\bblender\b.+\bdownload\b", low):
        actions = _download_blender()
        source = "scenario:download_blender"
    elif re.search(r"\bfill\b.+\bform\b|\bfill\s+(?:this\s+)?out\b", low):
        actions = _fill_form(raw)
        source = "scenario:fill_form"
    elif re.search(r"\bupload\b.+\bfile\b|\bupload\s+this\b", low):
        actions = _upload_file(raw)
        source = "scenario:upload_file"
    elif re.search(r"\bdiscord\b", low) and re.search(r"\b(send|message)\b", low):
        actions = _discord_message(raw)
        source = "scenario:discord_message"
    elif re.search(r"\b(?:navigate|open)\b.+\bsettings\b|\bwindows\s+settings\b", low):
        actions = _navigate_settings(raw)
        source = "scenario:navigate_settings"
    elif re.search(r"\bdrag\b.+\bto\b", low):
        actions = [
            _act("screen", "Locate drag source visually", {"request": raw, "force": True}),
            _act("vision", "Complete drag/drop via vision computer use", {"goal": raw}, confirm=True),
        ]
        source = "scenario:drag"
    else:
        # Generic: screen understand then vision computer_use
        actions = [
            _act("screen", f"Understand and act: {raw[:80]}", {"request": raw, "force": True}),
            _act(
                "vision",
                "Vision computer use fallback",
                {"goal": raw},
                expected="goal progress or done",
                confirm=True,
            ),
        ]
        source = "scenario:generic_vision"

    ms = round((time.perf_counter() - t0) * 1000, 2)
    return actions or [], source, ms


def _train_ticket(text: str) -> list[CUAction]:
    # IRCTC / generic train booking — browser first
    return [
        _act("open_website", "Open train booking site", {"url": "https://www.irctc.co.in/"}, expected="booking site open"),
        _act("wait", "Wait for page", {"seconds": 2}),
        _act("screen", "Find From/To or Login", {"request": "Find the Login or From station field", "force": True}),
        _act(
            "vision",
            "Book train ticket with vision assistance",
            {"goal": text or "Book a train ticket on this site"},
            confirm=True,
            expected="search form filled or ticket flow started",
        ),
    ]


def _download_blender() -> list[CUAction]:
    return [
        _act("open_app", "Open Chrome", {"name": "Chrome", "wait_seconds": 3}),
        _act("open_website", "Open Blender download", {"url": "https://www.blender.org/download/"}, expected="download page"),
        _act("screen", "Click Download", {"request": "Find the download button", "force": True}),
        _act(
            "vision",
            "Complete Blender download/install dialogs",
            {"goal": "Download Blender and start the installer if prompted"},
            confirm=True,
        ),
    ]


def _fill_form(text: str) -> list[CUAction]:
    return [
        _act("screen", "Locate form fields on screen", {"request": "What form fields are visible?", "force": True}),
        _act(
            "vision",
            "Fill the visible form",
            {"goal": text or "Fill this form with reasonable placeholder values"},
            confirm=True,
            expected="form fields filled",
        ),
    ]


def _upload_file(text: str) -> list[CUAction]:
    # Extract path if quoted or looks like a path
    path = ""
    m = re.search(r'["\']([^"\']+\.[A-Za-z0-9]{1,8})["\']', text)
    if m:
        path = m.group(1)
    if not path:
        m = re.search(r"((?:[A-Za-z]:\\|\\\\|~/|\./)[^\s]+)", text)
        if m:
            path = m.group(1)
    acts = [
        _act("screen", "Find Upload / Choose File control", {"request": "Click Upload or Choose File or Browse", "force": True}),
    ]
    if path:
        acts.append(_act("upload", f"Submit file {path}", {"path": path}, confirm=True, expected="file selected"))
    else:
        acts.append(
            _act(
                "vision",
                "Complete file upload dialog",
                {"goal": text or "Upload the file using the open file dialog"},
                confirm=True,
            )
        )
    return acts


def _discord_message(text: str) -> list[CUAction]:
    # Extract message body after "send" / "message"
    msg = ""
    m = re.search(r"(?:send|message)\s+(?:this\s+)?(?:message\s+)?[:\-–]?\s*[\"']?(.+?)[\"']?\s*$", text, re.I)
    if m:
        msg = m.group(1).strip()
        if msg.lower() in ("this message", "a message", "message"):
            msg = ""
    if not msg:
        msg = "Hello from NEURON"
    return [
        _act("open_app", "Open Discord", {"name": "Discord", "wait_seconds": 4}, expected="Discord running"),
        _act("wait", "Let Discord settle", {"seconds": 1.5}),
        _act("screen", "Focus message compose box", {"request": "Click the message input field", "force": True}),
        _act("type", "Type the message", {"text": msg}, confirm=True, expected="text entered"),
        _act("key", "Send message", {"keys": "enter"}, expected="message sent"),
    ]


def _navigate_settings(text: str) -> list[CUAction]:
    page = "home"
    low = text.lower()
    for key, val in (
        ("bluetooth", "bluetooth"),
        ("wifi", "network"),
        ("network", "network"),
        ("display", "display"),
        ("sound", "sound"),
        ("privacy", "privacy"),
        ("update", "windowsupdate"),
        ("apps", "appsfeatures"),
    ):
        if key in low:
            page = val
            break
    return [
        _act("tool", "Open Windows Settings", {"action": "open_settings", "args": {"page": page}}, expected="Settings open"),
        _act("screen", "Navigate settings pane", {"request": text, "force": True}),
    ]


def actions_to_taskgraph(text: str, actions: list[CUAction]):
    """Optional: convert CU actions to a TaskGraph for taskplan.run_graph."""
    try:
        from neuron.taskplan.extract import extract_goal
        from neuron.taskplan.types import Subtask, TaskGraph
        goal = extract_goal(text)
        steps: list[Subtask] = []
        prev = None
        for i, a in enumerate(actions):
            tool, args = _map_to_tool(a)
            if not tool:
                continue
            sid = f"st_cu_{i}"
            st = Subtask(
                description=a.description,
                action=tool,
                args=args,
                depends_on=[prev] if prev else [],
                expected_result=a.expected,
                requires_confirm=a.requires_confirm,
                use_screen=(tool == "screen_understand"),
                subtask_id=sid,
            )
            steps.append(st)
            prev = sid
        if not steps:
            return None
        return TaskGraph(goal=goal, subtasks=steps, source="computer_use")
    except Exception:
        return None


def _map_to_tool(a: CUAction) -> tuple[str, dict[str, Any]]:
    k = a.kind
    args = dict(a.args or {})
    if k == "open_app":
        return "open_app", args
    if k == "open_website":
        return "open_website", args
    if k == "type":
        return "type_text", args
    if k == "key":
        return "press_keys", args
    if k == "scroll":
        return "scroll", args
    if k == "screen":
        return "screen_understand", args
    if k == "upload":
        return "upload_file", args
    if k == "drag":
        return "drag_drop", args
    if k == "wait":
        return "wait", args
    if k == "tool":
        return str(args.get("action") or ""), dict(args.get("args") or {})
    if k == "vision":
        return "computer_use", {"goal": args.get("goal") or a.description}
    return "", {}
