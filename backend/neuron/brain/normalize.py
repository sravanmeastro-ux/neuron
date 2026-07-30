"""Normalize LLM plan JSON into executor steps.

Accepts both:
  {"tool": "open_app", "arguments": {"application": "Blender"}}
  {"action": "open_app", "args": {"name": "Blender"}}
"""

from __future__ import annotations

import json
import re
from typing import Any

# Common LLM arg aliases → canonical tool parameters
_ARG_ALIASES = {
    "application": "name",
    "app": "name",
    "program": "name",
    "exe": "name",
    "url": "site",
    "website": "site",
    "q": "query",
    "search": "query",
    "text_to_type": "text",
    "keys_to_press": "keys",
    "key": "keys",
    "section_name": "section",
    "monitor_id": "monitor",
    "display": "monitor",
    "screen": "monitor",
    "to_monitor": "monitor",
    "to_screen": "monitor",
}


def normalize_args(args: dict | None) -> dict:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        key = str(k).strip()
        canon = _ARG_ALIASES.get(key.lower(), key)
        if canon not in out or out[canon] in ("", None):
            out[canon] = v
    # Prefer name from application if both present empty name
    if not out.get("name") and out.get("application"):
        out["name"] = out["application"]
    return out


def normalize_step(step: Any) -> dict | None:
    if not isinstance(step, dict):
        if isinstance(step, str) and step.strip():
            return {"action": step.strip(), "args": {}}
        return None
    name = (
        step.get("tool")
        or step.get("action")
        or step.get("name")
        or step.get("fn")
        or ""
    )
    name = str(name).strip()
    if not name:
        return None
    args = step.get("arguments") or step.get("args") or step.get("params") or {}
    if not isinstance(args, dict):
        args = {}
    return {"action": name, "args": normalize_args(args)}


def normalize_plan(raw: Any) -> dict:
    """Return {say, steps:[{action,args}]} from messy LLM JSON."""
    if raw is None:
        return {"say": "", "steps": []}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}|\[.*\]", raw, re.S)
            if not m:
                return {"say": raw.strip(), "steps": []}
            try:
                raw = json.loads(m.group(0))
            except Exception:
                return {"say": raw.strip(), "steps": []}

    # Bare list of tool calls
    if isinstance(raw, list):
        steps = [s for s in (normalize_step(x) for x in raw) if s]
        return {"say": "", "steps": steps}

    if not isinstance(raw, dict):
        return {"say": "", "steps": []}

    say = (raw.get("say") or raw.get("reply") or raw.get("message") or "").strip()
    steps_raw = raw.get("steps") or raw.get("plan") or raw.get("tools") or raw.get("actions")
    if steps_raw is None and (raw.get("tool") or raw.get("action")):
        steps_raw = [raw]
    if not isinstance(steps_raw, list):
        steps_raw = []
    steps = [s for s in (normalize_step(x) for x in steps_raw) if s]
    return {"say": say, "steps": steps}
