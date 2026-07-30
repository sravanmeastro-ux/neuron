"""Planner — Ollama emits structured tool plans; never touches the OS."""

from __future__ import annotations

import json
import time
from typing import Any

import brain_llm
from neuron.brain import tool_registry
from neuron.brain.normalize import normalize_plan

PLANNER_SYSTEM = """You are NEURON's planner on a Windows PC.
You NEVER execute actions yourself. You only return STRICT JSON plans.

Output format ONLY:
{{"say":"<short spoken reply>","steps":[{{"tool":"<name>","arguments":{{...}}}}]}}

Rules:
- Use ONLY tools from the TOOLS list.
- Prefer 1-4 steps. Smallest correct plan.
- open desktop apps with open_app {{"name":"Blender"}} (also accept "application").
- Websites: browser_open / browser_navigate / browser_search — NEVER open_app for youtube/google/gmail.
- Generic web tasks (preferred):
  browser_search {{"site":"youtube","query":"..."}} then browser_find_element / browser_click for a result
  OR browser_click {{"index":0}} / first result from search state.
  For research questions: browser_research {{"query":"...","site":"google"}} (summarizes; sources in tool state).
- Existing YouTube helpers (play_result, youtube_home, …) remain valid shortcuts when already on YouTube.
- UI understanding (desktop): click_ui_element / get_ui_tree for native apps.
- Prefer DOM/a11y browser_* and UIA tools over click / move_mouse / computer_use.
- Screen understanding: analyze_screen / get_screen_context (UIA→OCR→local Ollama VLM). Never cloud vision.
- Coordinate mouse / vision computer_use only as last resort.
- CONTEXT_SNAPSHOT / RESOLVED_REFERENCES (Phase 8): when present, treat them as ground truth for deixis
  (it/that/this/first one/the X one/this page/that window). Prefer tool_hint + args_hint from RESOLVED_REFERENCES.
  Examples: YouTube + "play the first one" → browser_click index 0; Explorer + "open the Blender one" → click_ui_element name;
  Spotify + "pause it" → hotkey space (current playback).
- Do NOT invent which item "first/that" means — use snapshot UI/DOM labels. If unresolved, empty steps and ask in say.
- Never guess destructive actions (delete/uninstall/shutdown/close all) from vague deixis — ask in say, empty steps.
- Multi-monitor (Phase 10): get_monitors first when the user names a screen.
  Phrases: "screen 1", "screen 2", "left/right monitor", "main screen", "other screen".
  "Open YouTube on screen 1" → browser_open/search then move_window_to_monitor {{"name":"Chrome","monitor":"1"}} (or browser window title); verify after.
  "Move Blender to the other screen" → move_window_to_monitor {{"name":"Blender","monitor":"other"}}.
  Use get_windows_by_monitor / capture_monitor with the same NL monitor refs. Never invent resolutions — use live geometry from get_monitors.
- Empty steps only for pure chat or clarifying questions (answer in say).
- Never claim success in say without a step that does the work.
- Do not invent tools.
"""


def _log(msg: str) -> None:
    print(f"[planner] {msg}", flush=True)


def plan(request: str, context: str = "", normalized: str = "") -> dict | None:
    """Ask Ollama for a normalized plan using registry tool schemas."""
    if not brain_llm.is_enabled():
        _log("Ollama LLM disabled")
        return None

    tool_registry.ensure_bootstrapped()
    tools = tool_registry.tools_doc(70)
    user = request
    if normalized and normalized.strip().lower() != (request or "").strip().lower():
        user = f"User said: {request}\nNormalized intent: {normalized}"

    ctx = (context or "").strip()
    if len(ctx) > 2400:
        ctx = ctx[-2400:]

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM + "\n\nTOOLS:\n" + tools},
    ]
    if ctx:
        messages.append({"role": "system", "content": "CONTEXT:\n" + ctx})
    messages.append({"role": "user", "content": user})

    t0 = time.time()
    try:
        # Prefer dedicated planner chat; fall back to brain_llm.plan
        raw = brain_llm.chat_json(messages, timeout=_timeout())
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        _log(f"chat_json failed ({exc}); falling back to brain_llm.plan")
        data = brain_llm.plan(request, (tools + "\n\n" + ctx).strip(), normalized=normalized)
        if data is None:
            return None

    plan_out = normalize_plan(data)
    # Empty plan with no spoken reply = planner failed / nothing to do
    if not (plan_out.get("steps") or []) and not (plan_out.get("say") or "").strip():
        _log("empty plan from LLM")
        return None
    elapsed = time.time() - t0
    _log(
        f"planned {len(plan_out.get('steps') or [])} steps in {elapsed:.2f}s: "
        + json.dumps(plan_out.get("steps") or [], ensure_ascii=False)[:300]
    )
    return plan_out


def replan(
    request: str,
    context: str,
    failed_step: dict,
    error: str,
    normalized: str = "",
) -> dict | None:
    fix = (
        (context or "")
        + "\n\nPREVIOUS STEP FAILED (do not restart the whole goal)."
        + f"\nFailed step: {json.dumps(failed_step, ensure_ascii=False)}"
        + f"\nError: {error}"
        + "\nOBSERVE → DIAGNOSE → REPLAN from current state."
        + " Only return remaining steps. Prefer a different valid method."
        + " Prefer UI Automation / browser DOM over coordinates."
        + " If you cannot safely finish, empty steps + honest explanation in say."
        + " Never claim success without tools that will verify."
    )
    return plan(request, fix, normalized=normalized)


def _timeout() -> int:
    try:
        cfg = brain_llm._load_config().get("llm", {})
        return int(cfg.get("timeout_seconds", 25) or 25) + 10
    except Exception:
        return 30
