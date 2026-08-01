"""Centralized canary eligibility — allowlist by semantic intent, not phrases."""

from __future__ import annotations

import re
from typing import Any

# Stable semantic families (repository-supported)
CANARY_ALLOW_INTENTS = frozenset({
    "APP_OPEN",
    "WINDOW_FOCUS",
    "WINDOW_MOVE",
    "WINDOW_MAXIMIZE",
    "BROWSER_NAVIGATE",
    "YOUTUBE_SEARCH",
    "YOUTUBE_HOME",
    "VOLUME_SIMPLE",
    "MUTE",
    "OPEN",
    "FOCUS",
    "MOVE_MONITOR",
})

# Map IntentFamily / loose labels → canary family
_FAMILY_MAP = {
    "open": "APP_OPEN",
    "APP_OPEN": "APP_OPEN",
    "OPEN": "APP_OPEN",
    "focus": "WINDOW_FOCUS",
    "WINDOW_FOCUS": "WINDOW_FOCUS",
    "FOCUS": "WINDOW_FOCUS",
    "move_monitor": "WINDOW_MOVE",
    "WINDOW_MOVE": "WINDOW_MOVE",
    "MOVE_MONITOR": "WINDOW_MOVE",
    "maximize": "WINDOW_MAXIMIZE",
    "WINDOW_MAXIMIZE": "WINDOW_MAXIMIZE",
    "browser": "BROWSER_NAVIGATE",
    "BROWSER_NAVIGATE": "BROWSER_NAVIGATE",
    "navigate": "BROWSER_NAVIGATE",
    "youtube_search": "YOUTUBE_SEARCH",
    "YOUTUBE_SEARCH": "YOUTUBE_SEARCH",
    "youtube_home": "YOUTUBE_HOME",
    "YOUTUBE_HOME": "YOUTUBE_HOME",
    "volume": "VOLUME_SIMPLE",
    "VOLUME_SIMPLE": "VOLUME_SIMPLE",
    "mute": "MUTE",
    "MUTE": "MUTE",
}

_DENY_TOOLS = frozenset({
    "run_shell", "delete_file", "files.delete", "send_keys_raw",
    "type_password", "submit_form",
})

_DENY_RE = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|credential|delete|format|"
    r"rm\s+-rf|shutdown|restart|reboot|registry|install|purchase|payment|"
    r"buy\b|checkout|submit\b)\b"
)

_HIGH_RISK = frozenset({"high", "confirm", "blocked", "dangerous"})


def normalize_intent_family(family: str) -> str:
    f = (family or "").strip()
    if not f:
        return ""
    mapped = _FAMILY_MAP.get(f) or _FAMILY_MAP.get(f.upper()) or _FAMILY_MAP.get(f.lower())
    return mapped or f.upper()


def infer_intent_family(text: str, *, v4_family: str = "", intent_action: str = "") -> str:
    if v4_family:
        n = normalize_intent_family(v4_family)
        if n in CANARY_ALLOW_INTENTS or n in _FAMILY_MAP.values():
            return n if n in CANARY_ALLOW_INTENTS else normalize_intent_family(n)
        n2 = normalize_intent_family(v4_family)
        if n2 in CANARY_ALLOW_INTENTS:
            return n2
    t = (text or "").lower()
    act = (intent_action or "").lower()
    if act in ("open_app", "windows.open_app") or re.search(r"\bopen\b.+\b(chrome|edge|notepad|spotify|discord)\b", t):
        return "APP_OPEN"
    if act in ("focus_app", "windows.focus_app") or re.search(r"\bfocus\b|\bbring\b", t):
        return "WINDOW_FOCUS"
    if "monitor" in t and re.search(r"\b(move|put|send)\b", t):
        return "WINDOW_MOVE"
    if re.search(r"\bmaximize\b", t):
        return "WINDOW_MAXIMIZE"
    if "youtube" in t and re.search(r"\bsearch\b", t):
        return "YOUTUBE_SEARCH"
    if re.search(r"\b(go to|open)\b.+\byoutube\b|\byoutube\b.+\bhome\b", t):
        return "YOUTUBE_HOME"
    if re.search(r"\b(open|go to|navigate)\b.+\b(http|www\.|\.com|site)\b", t) or "open website" in t:
        return "BROWSER_NAVIGATE"
    if re.search(r"\b(mute|unmute)\b", t):
        return "MUTE"
    if re.search(r"\bvolume\b", t):
        return "VOLUME_SIMPLE"
    if v4_family:
        return normalize_intent_family(v4_family)
    return ""


def canary_eligible(
    *,
    text: str,
    intent_family: str = "",
    tools: list[str] | None = None,
    risk: str = "safe",
    stt_confidence: float | None = None,
    include_learned_procedures: bool = False,
) -> tuple[bool, str]:
    """Return (eligible, reason). Explicit deny beats allow."""
    tools = list(tools or [])
    fam = normalize_intent_family(intent_family) or infer_intent_family(text)

    if _DENY_RE.search(text or ""):
        return False, "deny: sensitive/destructive language"
    if any(t in _DENY_TOOLS for t in tools):
        return False, "deny: forbidden tool"
    if not include_learned_procedures:
        if any(
            (t.startswith("learned.") or t == "run_procedure")
            for t in tools
        ):
            return False, "deny: learned procedure excluded from initial canary"
    risk_l = (risk or "safe").lower()
    if risk_l in _HIGH_RISK or risk_l == "blocked":
        return False, f"deny: risk={risk_l}"
    if stt_confidence is not None and stt_confidence < 0.35:
        return False, "deny: low STT confidence"
    if not fam or fam not in CANARY_ALLOW_INTENTS:
        return False, f"deny: intent {fam or 'unknown'} not in canary allowlist"
    return True, f"allow: {fam}"


def canary_policy_snapshot() -> dict[str, Any]:
    return {
        "allow_intents": sorted(CANARY_ALLOW_INTENTS),
        "deny_tools": sorted(_DENY_TOOLS),
        "include_learned_procedures": False,
        "notes": "Allowlist by semantic intent family; exclude destructive/sensitive/learned.",
    }


__all__ = [
    "CANARY_ALLOW_INTENTS",
    "normalize_intent_family",
    "infer_intent_family",
    "canary_eligible",
    "canary_policy_snapshot",
]
