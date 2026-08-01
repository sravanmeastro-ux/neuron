"""Detect GitHub intelligence intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.github_agent.types import GitHubCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_GH = re.compile(
    r"\b("
    r"github|pull request|\bpr\b|merge conflict|changelog|release notes|"
    r"version tag|tag (a )?release|ci failed|github actions|workflow run|"
    r"review (my )?(last|latest) commit|generate (a )?changelog|"
    r"explain why ci|create (an )?issue|repo(sitory)? analysis|"
    r"monitor ci|ci/?cd"
    r")\b",
    re.I,
)


def looks_like_github(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("github ") or low in ("github status", "gh status"):
        return True
    return bool(_GH.search(t))


def classify_github_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if "github status" in low or low in ("gh status", "github agent"):
        return {"capability": GitHubCapability.STATUS.value, "args": {}}

    if re.search(r"\b(generate (a )?changelog|release notes)\b", low):
        return {"capability": GitHubCapability.CHANGELOG.value, "args": {}}

    if re.search(r"\b(ci failed|explain why ci|ci/?cd|github actions|workflow run|monitor ci)\b", low):
        return {"capability": GitHubCapability.CI.value, "args": {"text": t}}

    if re.search(r"\b(pull request|review (the )?pr|\bpr review)\b", low) or re.search(r"\bpr\b", low):
        m = re.search(r"#(\d+)", t)
        return {"capability": GitHubCapability.PR.value, "args": {"number": m.group(1) if m else None}}

    if "merge conflict" in low or "resolve conflict" in low:
        return {"capability": GitHubCapability.CONFLICTS.value, "args": {}}

    if re.search(r"\b(create (an )?issue|issue generation)\b", low):
        title = ""
        m = re.search(r"issue[:\s]+(.+)$", t, re.I)
        if m:
            title = m.group(1).strip()
        return {"capability": GitHubCapability.ISSUE.value, "args": {"title": title, "create": False}}

    if re.search(r"\b(version tag|tag (a )?release|tag version)\b", low):
        m = re.search(r"\bv?\d+\.\d+\.\d+\b", t)
        return {"capability": GitHubCapability.TAG.value, "args": {"tag": m.group(0) if m else None}}

    if re.search(r"\b(review (my )?(last|latest) commit|commit review)\b", low):
        return {"capability": GitHubCapability.COMMIT.value, "args": {"rev": "HEAD"}}

    if re.search(r"\b(repo(sitory)? analysis|analyze (the )?repo)\b", low):
        return {"capability": GitHubCapability.REPO.value, "args": {}}

    return {"capability": GitHubCapability.REPO.value, "args": {}}
