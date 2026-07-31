"""Normalize LLM plan JSON into executor steps.

Accepts both:
  {"tool": "open_app", "arguments": {"application": "Blender"}}
  {"action": "open_app", "args": {"name": "Blender"}}

Closed-loop enrichment (backward compatible):
  each step also gets target, expected_result, timeout, retry_limit.
"""

from __future__ import annotations

import json
import re
from typing import Any

from neuron.brain.step import DEFAULT_RETRY_LIMIT, DEFAULT_TIMEOUT, enrich_step_dict

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


def _defaults_from_config() -> tuple[float, int]:
    try:
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(
                encoding="utf-8"
            )
        ).get("agent") or {}
        timeout = float(cfg.get("tool_timeout_seconds", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)
        retry = int(cfg.get("max_step_retries", DEFAULT_RETRY_LIMIT) or DEFAULT_RETRY_LIMIT)
        return timeout, retry
    except Exception:
        return DEFAULT_TIMEOUT, DEFAULT_RETRY_LIMIT


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
            step = {"action": step.strip(), "args": {}}
        else:
            return None
    name = (
        step.get("tool")
        or step.get("action")
        or step.get("name")
        or step.get("fn")
        or ""
    )
    name = str(name).strip()
    # Resolve dotted ↔ underscore skill aliases without forcing dotted form.
    # If the caller wrote browser_search and both forms are registered, keep
    # browser_search (matches plans, expect_actions, and executor logs).
    if name:
        try:
            from neuron.brain import tool_registry
            tool_registry.ensure_bootstrapped()
            if "." in name:
                unders = name.replace(".", "_", 1)
                prefix = name.split(".", 1)[0]
                if prefix in (
                    "youtube", "browser", "windows", "spotify", "discord", "files", "blender",
                ):
                    if not tool_registry.get(name) and tool_registry.get(unders):
                        name = unders
            elif "_" in name:
                dotted = name.replace("_", ".", 1)
                prefix = dotted.split(".", 1)[0]
                if prefix in (
                    "youtube", "browser", "windows", "spotify", "discord", "files", "blender",
                ):
                    if not tool_registry.get(name) and tool_registry.get(dotted):
                        name = dotted
        except Exception:
            pass
    if not name:
        return None
    args = step.get("arguments") or step.get("args") or step.get("params") or {}
    if not isinstance(args, dict):
        args = {}
    base = {
        "action": name,
        "args": normalize_args(args),
    }
    # Preserve closed-loop fields from planner if present
    for key in ("target", "expected_result", "expect", "expected", "timeout",
                "timeout_seconds", "retry_limit", "retries"):
        if key in step and step[key] not in (None, ""):
            base[key] = step[key]
    default_timeout, default_retry = _defaults_from_config()
    return enrich_step_dict(base, default_timeout=default_timeout, default_retry=default_retry)


def normalize_plan(raw: Any) -> dict:
    """Return {say, steps:[{action,args,target,expected_result,timeout,retry_limit}]}."""
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
