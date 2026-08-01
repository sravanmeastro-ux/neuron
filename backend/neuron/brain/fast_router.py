"""Fast Intent Router — Category A desktop commands bypass AgentLoop.

Category A (deterministic): open apps, volume, media, clipboard, windows,
scroll, screenshots, lock, simple hotkeys, skip-ad, simple browser open.

Category B (reasoning): summarize, write, explain, research, multi-step,
ambiguous UI clicks → existing AgentLoop / LLM path.

Confidence bands:
  >= 0.95  → execute immediately (no observe / plan / verify)
  0.70–0.95 → lightweight validation then execute
  < 0.70   → AgentLoop

On fast-path failure → caller falls back to AgentLoop (never lose capability).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

# Capability IDs safe to run without AgentLoop observe/verify
_FAST_CAPABILITY_IDS = frozenset({
    "system.volume",
    "windows.open_app",
    "windows.focus_app",
    "windows.close_app",
    "windows.move_to_monitor",
    "input.copy",
    "input.paste",
    "input.escape",
    "input.hotkey",
    "input.type",
    "ui.scroll",
    "youtube.skip_ad",
    "youtube.home",
    "youtube.pause",
    "youtube.play",
    "youtube.fullscreen",
    "browser.open",
    "browser.open_url",
    "files.open_downloads",
    "files.open",
})

# Tools never executed on fast path (need perception / multi-step verify)
_SLOW_TOOLS = frozenset({
    "click_element",
    "click_ui_element",
    "find_element",
    "analyze_screen",
    "computer_use",
    "run_procedure",
    "browser_research",
    "play_result",  # ordinal video pick benefits from verify
    "search_site",  # YouTube search OK but multi-step play is slow
    "youtube_search",
})

_COMPLEX_RE = re.compile(
    r"\b("
    r"summarize|summary|summarise|"
    r"write\s+(?:an?\s+)?(?:email|essay|letter|story|paragraph|code)|"
    r"explain|describe\s+(?:this|the)\b|"
    r"research|analyze|analyse|analysis|"
    r"generate\s+(?:a\s+)?(?:python|code|script|image)|"
    r"find\s+(?:recent\s+)?news|"
    r"what\s+(?:do\s+you\s+think|should\s+i)|"
    r"help\s+me\s+(?:think|plan|decide|brainstorm)|"
    r"multi[\s-]?step|walk\s+me\s+through|"
    r"creative|poem|lyrics|"
    r"compare\s+(?:and\s+contrast)|"
    r"debug\s+(?:this\s+)?code|"
    r"refactor"
    r")\b",
    re.I,
)

# Extra Category A patterns not always covered by CapabilityRouter
_EXTRA_PATTERNS: list[tuple[re.Pattern[str], str, dict[str, Any], float]] = [
    (re.compile(r"^(?:please\s+)?(?:undo)(?:\s+that)?[.!]?$", re.I),
     "press_keys", {"keys": "ctrl+z"}, 0.97),
    (re.compile(r"^(?:please\s+)?(?:redo)(?:\s+that)?[.!]?$", re.I),
     "press_keys", {"keys": "ctrl+y"}, 0.97),
    (re.compile(
        r"\b(?:take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|"
        r"screenshot(?:\s+(?:please|now))?)\b",
        re.I,
    ), "get_active_window_screenshot", {}, 0.96),
    (re.compile(r"\b(?:lock\s+(?:the\s+)?(?:pc|computer|workstation|screen)|win(?:dows)?\s*\+\s*l)\b", re.I),
     "_hotkey", {"keys": ["win", "l"]}, 0.97),
    (re.compile(r"^(?:please\s+)?(?:show\s+(?:the\s+)?desktop|go\s+to\s+desktop)[.!]?$", re.I),
     "_window", {"action": "desktop"}, 0.96),
    (re.compile(r"^(?:please\s+)?(?:minimize|minimise)(?:\s+(?:the\s+)?window)?[.!]?$", re.I),
     "_window", {"action": "minimize"}, 0.95),
    (re.compile(r"^(?:please\s+)?(?:maximize|maximise)(?:\s+(?:the\s+)?window)?[.!]?$", re.I),
     "_window", {"action": "maximize"}, 0.95),
    (re.compile(r"^(?:please\s+)?(?:switch\s+window|alt\s*tab|next\s+window)[.!]?$", re.I),
     "_window", {"action": "switch"}, 0.94),
    (re.compile(
        r"\b(?:media\s+)?(?:play|pause|resume)(?:\s+(?:music|media|song|track|video))?\b",
        re.I,
    ), "_media", {"action": "playpause"}, 0.93),
    (re.compile(r"\b(?:next\s+(?:track|song|video)|skip\s+(?:track|song))\b", re.I),
     "_media", {"action": "next"}, 0.94),
    (re.compile(r"\b(?:previous|last|prev)\s+(?:track|song|video)\b", re.I),
     "_media", {"action": "previous"}, 0.94),
    (re.compile(r"\b(?:scroll)\s+(up|down|left|right)\b", re.I),
     "scroll", {"direction": None}, 0.94),  # direction filled at match time
]


@dataclass
class FastDecision:
    category: str  # A | B | none
    confidence: float = 0.0
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    capability_id: str = ""
    reason: str = ""
    band: str = ""  # immediate | light | agent


@dataclass
class FastResult:
    ok: bool
    say: str | None = None
    acted: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    used_agent_loop: bool = False


def _is_complex(text: str) -> bool:
    return bool(_COMPLEX_RE.search(text or ""))


def _result_to_say(out: Any) -> tuple[str, bool]:
    """Normalize tool output → (message, success)."""
    if out is None:
        return "Done.", True
    if hasattr(out, "success"):
        ok = bool(getattr(out, "success", False))
        msg = str(out) if out else ("Done." if ok else "Failed.")
        return msg, ok
    if isinstance(out, dict):
        ok = bool(out.get("ok", out.get("success", True)))
        msg = str(out.get("message") or out.get("say") or out.get("error") or "Done.")
        return msg, ok
    return str(out), True


def _light_validate(tool: str, args: dict[str, Any]) -> tuple[bool, str]:
    """Cheap pre-checks for mid-confidence band. No screen observe."""
    if tool == "open_app":
        name = (args.get("name") or args.get("application") or "").strip()
        if not name:
            return False, "missing app name"
        try:
            from neuron.windows.resolve import resolve
            r = resolve(name)
            if not r or not (getattr(r, "launch_target", None) or getattr(r, "canonical", None)):
                return False, f"unknown app:{name}"
        except Exception as exc:
            return False, str(exc)
        return True, "resolved"
    if tool in ("press_keys", "hotkey", "_hotkey", "_window", "_media", "volume", "scroll"):
        return True, "deterministic"
    if tool in ("close_app", "focus_app"):
        name = (args.get("name") or "").strip()
        return (bool(name), "has name" if name else "missing name")
    if tool.startswith("browser") or tool in ("open_website", "skip_ad", "youtube_home", "fullscreen"):
        return True, "browser"
    if tool == "get_active_window_screenshot":
        return True, "screenshot"
    if tool == "type_text":
        return bool((args.get("text") or "").strip()), "has text"
    return True, "default"


def _band(confidence: float) -> str:
    if confidence >= 0.95:
        return "immediate"
    if confidence >= 0.70:
        return "light"
    return "agent"


def classify(text: str, *, intent: Any | None = None) -> FastDecision:
    """Classify utterance into Category A/B and attach tool steps if A."""
    raw = (text or "").strip()
    if not raw:
        return FastDecision(category="none", reason="empty")

    if _is_complex(raw):
        return FastDecision(
            category="B",
            confidence=0.99,
            reason="complex_language",
            band="agent",
        )

    # Prefer CapabilityRouter patterns (reuse existing deterministic map)
    try:
        from neuron.v3 import capability_router as cap_mod
        routed = cap_mod.route(raw, intent=intent, min_confidence=0.70)
        if routed.ok and routed.capability and routed.steps:
            cid = routed.capability.id or ""
            tool = routed.capability.tool or (routed.steps[0].get("tool") or "")
            conf = float(routed.capability.confidence or 0.0)
            # Multi-app / perception tools → AgentLoop
            if cid == "multi_app.workflow" or tool in _SLOW_TOOLS:
                return FastDecision(
                    category="B",
                    confidence=conf,
                    capability_id=cid,
                    tool=tool,
                    reason="needs_agent_loop",
                    band="agent",
                )
            if cid in _FAST_CAPABILITY_IDS or (
                tool not in _SLOW_TOOLS
                and cid.split(".")[0] in ("system", "windows", "input", "ui", "youtube", "browser", "files")
                and len(routed.steps) == 1
            ):
                step = dict(routed.steps[0])
                args = dict(step.get("arguments") or step.get("args") or routed.capability.args or {})
                if tool == "open_app":
                    args.setdefault("wait_seconds", 2.5)
                step["arguments"] = args
                if "args" in step:
                    step["args"] = args
                return FastDecision(
                    category="A",
                    confidence=conf,
                    tool=tool,
                    args=args,
                    steps=[step],
                    capability_id=cid,
                    reason="capability_router",
                    band=_band(conf),
                )
    except Exception as exc:
        # Fall through to extras
        _ = exc

    # Extra Category A patterns
    low = raw.lower().strip()
    for cre, tool, base_args, conf in _EXTRA_PATTERNS:
        m = cre.search(low)
        if not m:
            continue
        args = dict(base_args)
        if tool == "scroll" and m.lastindex:
            args["direction"] = (m.group(1) or "down").lower()
        return FastDecision(
            category="A",
            confidence=conf,
            tool=tool,
            args=args,
            steps=[{"tool": tool, "arguments": args}],
            capability_id=f"fast.{tool}",
            reason="extra_pattern",
            band=_band(conf),
        )

    # Deterministic intent kinds from NLU/intent module
    if intent is not None:
        kind = getattr(intent, "kind", "") or ""
        action = getattr(intent, "action", "") or ""
        if kind in ("recipe", "deterministic") and action and action not in _SLOW_TOOLS:
            conf = 0.92
            args = dict(getattr(intent, "args", None) or {})
            if action == "open_app":
                args.setdefault("wait_seconds", 2.5)
            return FastDecision(
                category="A",
                confidence=conf,
                tool=action,
                args=args,
                steps=[{"tool": action, "arguments": args}],
                capability_id=f"intent.{action}",
                reason="intent_deterministic",
                band=_band(conf),
            )

    return FastDecision(category="B", confidence=0.0, reason="unmatched", band="agent")


def _exec_special(tool: str, args: dict[str, Any]) -> Any:
    if tool == "_hotkey":
        import pyautogui
        keys = args.get("keys") or []
        if isinstance(keys, str):
            keys = keys.replace("+", " ").split()
        pyautogui.hotkey(*[str(k) for k in keys])
        return f"Hotkey {'+'.join(str(k) for k in keys)}."
    if tool == "_window":
        import actions
        return actions.window(str(args.get("action") or "switch"))
    if tool == "_media":
        import actions
        return actions.media(str(args.get("action") or "playpause"))
    raise ValueError(f"unknown special tool {tool}")


def execute_steps(
    steps: list[dict[str, Any]],
    *,
    confirmed: bool = False,
    timeout_s: float = 8.0,
) -> FastResult:
    """Run tool steps directly via ToolRegistry — no AgentLoop."""
    from neuron.brain import tool_registry

    tool_registry.ensure_bootstrapped()
    t0 = time.perf_counter()
    last_say = "Done."
    for step in steps:
        tool = (step.get("tool") or step.get("action") or "").strip()
        args = dict(step.get("arguments") or step.get("args") or {})
        if not tool:
            continue
        if tool in _SLOW_TOOLS:
            return FastResult(
                ok=False,
                say=None,
                acted=False,
                meta={"error": f"slow_tool:{tool}", "used_agent_loop": False},
            )
        try:
            if tool.startswith("_"):
                out = _exec_special(tool, args)
            else:
                # Soft timeout via registry execute (sync); open_app already short-waits
                out = tool_registry.execute(tool, args, confirmed=confirmed)
            say, ok = _result_to_say(out)
            last_say = say
            if not ok:
                return FastResult(
                    ok=False,
                    say=say,
                    acted=True,
                    meta={
                        "error": say,
                        "tool": tool,
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "used_agent_loop": False,
                        "path": "fast_router",
                    },
                )
        except PermissionError as exc:
            return FastResult(
                ok=False,
                say=str(exc),
                acted=False,
                meta={"error": str(exc), "needs_confirm": True, "path": "fast_router"},
            )
        except Exception as exc:
            return FastResult(
                ok=False,
                say=str(exc),
                acted=False,
                meta={"error": str(exc), "tool": tool, "path": "fast_router"},
            )

    return FastResult(
        ok=True,
        say=last_say,
        acted=True,
        meta={
            "path": "fast_router",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
            "used_agent_loop": False,
        },
    )


def try_handle(
    text: str,
    *,
    intent: Any | None = None,
    confirmed: bool = False,
) -> FastResult | None:
    """
    Attempt Category A fast execution.

    Returns:
      FastResult on handled Category A (ok True/False)
      None if Category B / should use AgentLoop (caller must continue)
    """
    decision = classify(text, intent=intent)
    if decision.category != "A" or decision.band == "agent":
        return None

    if decision.band == "light":
        ok, why = _light_validate(decision.tool, decision.args)
        if not ok:
            return FastResult(
                ok=False,
                say=None,
                acted=False,
                meta={
                    "path": "fast_router",
                    "light_validation_failed": why,
                    "capability": decision.capability_id,
                    "confidence": decision.confidence,
                    # Signal caller to fall back to AgentLoop
                    "fallback_agent": True,
                },
            )

    steps = decision.steps or [{"tool": decision.tool, "arguments": decision.args}]
    result = execute_steps(steps, confirmed=confirmed)
    result.meta.update({
        "capability": decision.capability_id,
        "confidence": decision.confidence,
        "band": decision.band,
        "reason": decision.reason,
        "category": "A",
        "used_agent_loop": False,
    })
    if not result.ok:
        result.meta["fallback_agent"] = True
    return result


def should_skip_glance(text: str) -> bool:
    d = classify(text)
    return d.category == "A" and d.band in ("immediate", "light")
