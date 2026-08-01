"""Detect multi-step workflow requests vs single commands / control utterances."""

from __future__ import annotations

import re

# Pure Category-A style commands — never claim as workflows
_SINGLE_FAST = re.compile(
    r"^(?:mute|unmute|volume\s+(?:up|down)|copy|paste|undo|"
    r"open\s+[\w .+-]{1,40}|close\s+[\w .+-]{1,40}|focus\s+[\w .+-]{1,40})"
    r"(?:\s+please)?[.!?]?$",
    re.I,
)

_CANCEL = re.compile(
    r"^\s*(?:cancel(?:\s+(?:that|it|the\s+task|task))?|stop(?:\s+(?:that|it|the\s+task))?|"
    r"abort(?:\s+task)?|never\s*mind)\s*[.!]?\s*$",
    re.I,
)

_RESUME = re.compile(
    r"^\s*(?:resume(?:\s+(?:the\s+)?task)?|continue(?:\s+(?:the\s+)?task)?|"
    r"keep\s+going|pick\s+up\s+where\s+you\s+left\s+off)\s*[.!]?\s*$",
    re.I,
)

_CONFIRM = re.compile(
    r"^\s*(?:confirm|yes|go\s+ahead|do\s+it|proceed|approved?)\s*[.!]?\s*$",
    re.I,
)

_WORKFLOW_HINT = re.compile(
    r"\b(?:then|after\s+that|and\s+then|finally)\b|"
    r"\b(?:download|install|create|move|zip|archive|reply|write|run)\b.+\b(?:and|then)\b|"
    r"\bopen\b.+\b(?:search|play|create|write|reply|move|zip|install)\b",
    re.I,
)


def is_cancel_command(text: str) -> bool:
    return bool(_CANCEL.match((text or "").strip()))


def is_resume_command(text: str) -> bool:
    return bool(_RESUME.match((text or "").strip()))


def is_confirm_command(text: str) -> bool:
    return bool(_CONFIRM.match((text or "").strip()))


def looks_like_workflow(text: str) -> bool:
    """True when the utterance should use the Task Planning Engine."""
    t = (text or "").strip()
    if not t or len(t) < 18:
        return False
    if _SINGLE_FAST.match(t):
        return False
    if is_cancel_command(t) or is_resume_command(t) or is_confirm_command(t):
        return False
    # Clause / conjunction density
    clauses = re.split(r"\b(?:and|,|;|\bthen\b)\b", t, flags=re.I)
    clauses = [c.strip() for c in clauses if c.strip()]
    verbs = 0
    for c in clauses:
        if re.search(
            r"\b(open|launch|start|search|find|play|watch|download|install|"
            r"create|write|run|reply|archive|move|zip|close|focus|type)\b",
            c,
            re.I,
        ):
            verbs += 1
    if verbs >= 2 and len(clauses) >= 2:
        return True
    if _WORKFLOW_HINT.search(t) and verbs >= 2:
        return True
    # Multi-app helper (call without importing heavy deps)
    try:
        from neuron.v3.multi_app import looks_multi_app
        if looks_multi_app(t):
            return True
    except Exception:
        pass
    return False
