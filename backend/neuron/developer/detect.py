"""Detect software-engineering intents — never steal Category A FastIntent."""

from __future__ import annotations

import re
from typing import Any

from neuron.developer.types import DevCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|focus\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_DEV = re.compile(
    r"\b("
    r"create (a )?react|react app|fix (this )?(compile |build )?error|"
    r"review (my )?(latest )?commit|run (the )?(unit )?tests?|"
    r"explain (this )?(stack )?trace|generate (docs|documentation)|"
    r"refactor (this )?class|find (the )?bug|localize|optimize (this )?code|"
    r"code review|dependency graph|index (the )?(project|repo|repository)|"
    r"project index|compiler|stack trace|unit tests?|developer mode|"
    r"git status|git log|git diff|github|dockerfile|docker compose|"
    r"open (in )?(cursor|vs\s*code|visual studio)|cargo (build|test)|"
    r"npm (test|run|build)|pytest|dotnet (build|test)|mvn |"
    r"analyze (this |the )?(code|project|repo)|scaffold|create (a )?(python|rust|electron)"
    r")\b",
    re.I,
)


def looks_like_developer(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("dev ") or low.startswith("developer "):
        return True
    return bool(_DEV.search(t))


def classify_dev_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if "developer mode" in low or low in ("dev status", "developer status"):
        return {"capability": DevCapability.STATUS.value, "args": {}, "text": t}

    if re.search(r"\b(index (the )?(project|repo)|project index|repository understanding)\b", low):
        return {"capability": DevCapability.INDEX.value, "args": {}, "text": t}

    if "dependency" in low or "deps" in low:
        return {"capability": DevCapability.DEPS.value, "args": {}, "text": t}

    if re.search(r"\b(analyze|code analysis|understand (this )?project)\b", low):
        return {"capability": DevCapability.ANALYZE.value, "args": {}, "text": t}

    if re.search(r"\b(run (the )?(unit )?tests?|pytest|npm test|cargo test|dotnet test)\b", low):
        run = "npm test" if "npm" in low else ("pytest -q" if "pytest" in low or "python" in low else "")
        return {"capability": DevCapability.TEST.value, "args": {"run": True, "cmd": run}, "text": t}

    if re.search(r"\b(build|compile|npm run build|cargo build|dotnet build)\b", low) and "error" not in low:
        return {"capability": DevCapability.BUILD.value, "args": {"run": "run" in low or "build" in low}, "text": t}

    if re.search(r"\b(fix (this )?(compile |build )?error|compiler|diagnostics|stack trace)\b", low):
        return {"capability": DevCapability.DIAGNOSTICS.value, "args": {"text": t}, "text": t}

    if re.search(r"\b(explain)\b", low):
        return {"capability": DevCapability.EXPLAIN.value, "args": {"text": t}, "text": t}

    if re.search(r"\b(find (the )?bug|localize|bug)\b", low):
        return {"capability": DevCapability.BUGS.value, "args": {"text": t}, "text": t}

    if "refactor" in low or "optimize this code" in low:
        return {"capability": DevCapability.REFACTOR.value, "args": {"text": t}, "text": t}

    if re.search(r"\b(review (my )?(latest )?commit|git (status|log|diff)|github)\b", low):
        return {"capability": DevCapability.GIT.value, "args": {"op": "review" if "review" in low or "commit" in low else "status"}, "text": t}

    if re.search(r"\b(generate (docs|documentation)|documentation)\b", low):
        return {"capability": DevCapability.DOCS.value, "args": {}, "text": t}

    if re.search(r"\b(create (a )?react|scaffold|create (a )?(python|rust|electron)|react app)\b", low):
        return {"capability": DevCapability.SCAFFOLD.value, "args": {"goal": t}, "text": t}

    if re.search(r"\b(open (in )?(cursor|vs\s*code|visual studio)|cursor|vs code)\b", low):
        ide = "cursor" if "cursor" in low else ("code" if "vs" in low or "code" in low else "devenv")
        return {"capability": DevCapability.IDE.value, "args": {"ide": ide}, "text": t}

    return {"capability": DevCapability.ANALYZE.value, "args": {}, "text": t}
