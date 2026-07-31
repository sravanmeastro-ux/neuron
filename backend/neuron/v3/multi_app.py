"""V3.8 — multi-application staged goals.

Compose observe→act→verify plans that span several apps/monitors, e.g.:

  Open Chrome on monitor 2, search YouTube for Blender animation tutorials,
  play the first result, and open Blender on monitor 1.

Uses live monitor NL tokens (never hardcodes display coordinates).
Each stage carries expected_result so AgentLoop can verify independently.
"""

from __future__ import annotations

import re
from typing import Any


_APP_ALIASES = {
    "chrome": "Chrome",
    "google chrome": "Chrome",
    "edge": "Edge",
    "firefox": "Firefox",
    "blender": "Blender",
    "notepad": "Notepad",
    "spotify": "Spotify",
    "discord": "Discord",
    "code": "Code",
    "vscode": "Code",
    "cursor": "Cursor",
}


def looks_multi_app(text: str) -> bool:
    """True when the utterance likely needs staged multi-app planning."""
    t = (text or "").strip().lower()
    if not t or len(t) < 20:
        return False
    # Multiple conjuncts / clauses
    clauses = re.split(r"\b(?:and|,|;|\bthen\b)\b", t)
    clauses = [c.strip() for c in clauses if c.strip()]
    if len(clauses) < 2:
        return False
    verbs = 0
    for c in clauses:
        if re.search(
            r"\b(open|launch|start|search|find|play|watch|move|focus|close)\b",
            c,
        ):
            verbs += 1
    apps = _mentioned_apps(t)
    monitors = len(re.findall(r"\b(?:monitor|screen|display)\b", t))
    return verbs >= 2 and (len(apps) >= 2 or (len(apps) >= 1 and monitors >= 1 and verbs >= 3))


def compose_multi_app_plan(text: str) -> dict[str, Any] | None:
    """
    Build a staged plan with target + expected_result per step.
    Returns None if the utterance is not a recognizable multi-app workflow.
    """
    raw = (text or "").strip()
    if not looks_multi_app(raw):
        return None

    t = raw.lower()
    steps: list[dict[str, Any]] = []

    # Stage: open <app> on monitor <ref>
    for m in re.finditer(
        r"\bopen\s+([a-z0-9 .+-]{2,40}?)\s+"
        r"(?:on|to|onto)\s+(?:the\s+|my\s+)?"
        r"(?:monitor|screen|display)\s*"
        r"(one|two|three|four|five|first|second|third|\d{1,2}"
        r"|left|right|main|other|primary|foreground|current)",
        t,
    ):
        app = _canon_app(m.group(1))
        mon = _norm_mon(m.group(2))
        steps.extend(_open_on_monitor(app, mon))

    # Also: open <app> without monitor (if not already covered)
    for m in re.finditer(r"\bopen\s+([a-z0-9 .+-]{2,40})(?!\s+(?:on|to|onto)\s)", t):
        app_raw = m.group(1).strip()
        # Skip website-only opens already handled as chrome/browser
        if app_raw in ("youtube", "yt", "google", "gmail"):
            continue
        app = _canon_app(app_raw)
        if any(
            s.get("action") == "open_app" and (s.get("args") or {}).get("name") == app
            for s in steps
        ):
            continue
        # Avoid duplicating when "open X on monitor" already matched longer span
        if re.search(
            rf"\bopen\s+{re.escape(app_raw)}\s+(?:on|to|onto)\s+(?:the\s+|my\s+)?"
            r"(?:monitor|screen|display)",
            t,
        ):
            continue
        steps.append({
            "action": "open_app",
            "args": {"name": app},
            "target": app,
            "expected_result": f"app '{app}' is running or has a visible window",
            "stage": f"open_{app.lower()}",
        })

    # YouTube / browser search
    m = re.search(
        r"\bsearch\s+(?:on\s+)?(?:youtube|yt)\s+(?:for\s+)?(.+?)(?=\s*(?:,|and|;|\bplay\b|\bopen\b|$))",
        t,
    )
    if not m:
        m = re.search(
            r"\b(?:youtube|yt)\s+search\s+(?:for\s+)?(.+?)(?=\s*(?:,|and|;|\bplay\b|\bopen\b|$))",
            t,
        )
    if m:
        query = m.group(1).strip(" .,!?")
        # Drop trailing "play the first…" if captured
        query = re.sub(r"\s+play\b.*$", "", query).strip(" .,")
        if query:
            steps.append({
                "action": "browser_search",
                "args": {"site": "youtube", "query": query},
                "target": "youtube",
                "expected_result": f"search results for '{query}' are visible",
                "stage": "youtube_search",
            })

    # Play first/Nth result
    m = re.search(r"\bplay\s+(?:the\s+)?(first|1st|second|2nd|third|3rd|\d+)(?:\s+result|\s+video)?\b", t)
    if m:
        word = m.group(1)
        idx_map = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}
        idx = idx_map.get(word)
        if idx is None:
            try:
                n = int(word)
                idx = max(0, n - 1)
            except ValueError:
                idx = 0
        steps.append({
            "action": "play_result",
            "args": {"index": idx},
            "target": f"result {idx}",
            "expected_result": "video playing or result opened",
            "stage": "play_result",
        })

    # Move existing window (if not already covered via open-on-monitor)
    for m in re.finditer(
        r"\bmove\s+([a-z0-9 .+-]{2,40}?)\s+"
        r"(?:to|onto)\s+(?:the\s+|my\s+)?"
        r"(?:monitor|screen|display)\s*"
        r"(one|two|three|four|five|first|second|third|\d{1,2}"
        r"|left|right|main|other|primary|foreground|current)",
        t,
    ):
        app = _canon_app(m.group(1))
        mon = _norm_mon(m.group(2))
        if any(
            s.get("action") == "move_window_to_monitor"
            and (s.get("args") or {}).get("name") == app
            and str((s.get("args") or {}).get("monitor")) == str(mon)
            for s in steps
        ):
            continue
        steps.append({
            "action": "move_window_to_monitor",
            "args": {"name": app, "monitor": mon},
            "target": app,
            "expected_result": f"{app} window center on monitor {mon}",
            "stage": f"move_{app.lower()}",
        })

    if len(steps) < 2:
        return None

    # Deduplicate consecutive identical open_app
    deduped: list[dict] = []
    for s in steps:
        if deduped and deduped[-1].get("action") == s.get("action") and (
            deduped[-1].get("args") or {}
        ) == (s.get("args") or {}):
            continue
        deduped.append(s)

    apps = sorted({(s.get("args") or {}).get("name") for s in deduped if s.get("action") == "open_app"} - {None})
    say = "Working through that across " + (", ".join(apps) if apps else "your apps") + "."
    return {
        "say": say,
        "steps": deduped,
        "meta": {"multi_app": True, "stages": [s.get("stage") for s in deduped]},
    }


def _open_on_monitor(app: str, mon: str | int) -> list[dict[str, Any]]:
    return [
        {
            "action": "open_app",
            "args": {"name": app},
            "target": app,
            "expected_result": f"app '{app}' is running or has a visible window",
            "stage": f"open_{app.lower()}",
        },
        {
            "action": "move_window_to_monitor",
            "args": {"name": app, "monitor": mon},
            "target": app,
            "expected_result": f"{app} window center on monitor {mon}",
            "stage": f"place_{app.lower()}",
        },
    ]


def _mentioned_apps(t: str) -> list[str]:
    found = []
    for alias in _APP_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", t):
            found.append(_APP_ALIASES[alias])
    # unique preserve order
    out = []
    for a in found:
        if a not in out:
            out.append(a)
    return out


def _canon_app(raw: str) -> str:
    key = re.sub(r"\s+", " ", (raw or "").strip().lower())
    # Truncate trailing junk
    key = re.split(r"\s+(?:on|to|onto|and|then|,)\b", key)[0].strip()
    return _APP_ALIASES.get(key) or key.title()


def _norm_mon(token: str) -> str | int:
    tok = (token or "").strip().lower()
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "first": 1, "second": 2, "third": 3,
    }
    if tok in words:
        return words[tok]
    if re.fullmatch(r"\d{1,2}", tok):
        return int(tok)
    # Preserve relative NL tokens for geometry resolve at act time
    if tok in (
        "left", "right", "main", "other", "primary",
        "foreground", "current", "this", "secondary",
    ):
        return tok
    try:
        from neuron.windows.monitors import normalize_monitor_arg
        return normalize_monitor_arg(tok) or tok
    except Exception:
        return tok
