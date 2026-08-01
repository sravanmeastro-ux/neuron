"""Synonym maps — verbs and app/site aliases → canonical FastIntent forms."""

from __future__ import annotations

import re

OPEN_VERBS = (
    r"open|launch|start|run|execute|boot|bring\s+up|pull\s+up|fire\s+up|"
    r"spin\s+up|load|"
    r"get\s+(?:me\s+)?"
)

# Soft paraphrases → rewritten templates
PARAPHRASE_RULES: list[tuple[str, str, str]] = [
    (r"^(?:open\s+)?(?:the\s+)?browser$", "open chrome", "OPEN_APPLICATION"),
    (r"^(?:launch|start|run)\s+(?:the\s+)?browser$", "open chrome", "OPEN_APPLICATION"),
    (r"^let'?s\s+browse$", "open chrome", "OPEN_APPLICATION"),
    (r"^(?:i\s+want\s+to\s+)?browse(?:\s+the\s+web)?$", "open chrome", "OPEN_APPLICATION"),
    (r"^take\s+me\s+(?:to\s+)?(?:the\s+)?(?:web|internet)$", "open chrome", "OPEN_APPLICATION"),
    (r"^(?:i\s+need\s+)?google$", "open google", "OPEN_WEBSITE"),
    (r"^(?:open|launch|go\s+to)\s+google$", "open google", "OPEN_WEBSITE"),
    (r"^search\s+google\s+for\s+(.+)$", r"search the web for \1", "WEB_SEARCH"),
    (r"^take\s+me\s+to\s+(?:youtube|yt)$", "open youtube", "OPEN_WEBSITE"),
    (r"^(?:go\s+to|open|launch)\s+(?:youtube|yt)$", "open youtube", "OPEN_WEBSITE"),
    (r"^(?:youtube|yt)$", "open youtube", "OPEN_WEBSITE"),
    (r"^search\s+for\s+(.+)$", r"search for \1", "SEARCH"),
    (r"^find\s+(?:me\s+)?(.+)$", r"search for \1", "SEARCH"),
    (r"^look\s+up\s+(.+)$", r"search for \1", "SEARCH"),
    (r"^look\s+for\s+(.+)$", r"search for \1", "SEARCH"),
    (r"^i\s+need\s+(.+)$", r"open \1", "OPEN_APPLICATION"),
    (r"^i\s+want\s+(.+)$", r"open \1", "OPEN_APPLICATION"),
    (rf"^({OPEN_VERBS})\s+(.+)$", r"open \2", "OPEN_APPLICATION"),
    (r"^(?:close|quit|exit|kill)\s+(.+)$", r"close \1", "CLOSE_APPLICATION"),
    (r"^(?:focus|switch\s+to|bring\s+to\s+front|activate)\s+(.+)$", r"focus \1", "FOCUS_APPLICATION"),
    (r"^(?:turn\s+(?:it\s+)?up|make\s+(?:it\s+)?louder)$", "volume up", "VOLUME"),
    (r"^(?:turn\s+(?:it\s+)?down|make\s+(?:it\s+)?quieter)$", "volume down", "VOLUME"),
    (r"^(?:silence(?:\s+it)?)$", "mute", "VOLUME"),
    (r"^make\s+(?:it\s+)?(?:bigger|larger|maximize(?:d)?)$", "maximize", "WINDOW"),
    (r"^make\s+(?:it\s+)?(?:smaller|minimize(?:d)?)$", "minimize", "WINDOW"),
    (r"^(?:lock\s+(?:my\s+)?(?:pc|computer|screen)|lock\s+it)$", "lock the pc", "SYSTEM"),
]

APP_ALIASES: dict[str, str] = {
    "browser": "chrome",
    "the browser": "chrome",
    "web browser": "chrome",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "ms edge": "edge",
    "microsoft edge": "edge",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "code": "vscode",
    "unreal": "unreal engine",
    "ue5": "unreal engine",
    "roblox": "roblox studio",
    "file explorer": "explorer",
    "files": "explorer",
}

SITE_ALIASES: dict[str, str] = {
    "yt": "youtube",
    "you tube": "youtube",
    "google.com": "google",
}


def apply_paraphrase(text: str) -> tuple[str, str, float]:
    """Return (rewritten, intent_hint, rule_confidence)."""
    t = (text or "").strip()
    if not t:
        return t, "UNKNOWN", 0.0
    for pat, repl, hint in PARAPHRASE_RULES:
        if re.match(pat, t, flags=re.I):
            out = re.sub(pat, repl, t, count=1, flags=re.I).strip()
            out = re.sub(r"\s+", " ", out).strip(" .!?")
            # Avoid rewriting "start recording"
            if hint == "OPEN_APPLICATION" and re.match(
                r"^open\s+(?:recording|watching|listening)\b", out, re.I
            ):
                continue
            return out, hint, 0.93
    return t, "UNKNOWN", 0.0


def canonicalize_app(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    n = re.sub(r"^(?:the|my|a|an)\s+", "", n)
    return APP_ALIASES.get(n, n)


def canonicalize_site(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    return SITE_ALIASES.get(n, n)
