"""N.E.U.R.O.N long-term memory — simple persistent JSON store.

Keeps facts/preferences across sessions and a rolling recent-history log,
so the assistant remembers you without re-explaining every time.
"""

import json
from datetime import datetime
from pathlib import Path

STORE = Path(__file__).resolve().parent / "memory_store.json"
MAX_HISTORY = 40


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"facts": {}, "history": []}


def _save(data: dict) -> None:
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def remember(key: str, value: str) -> None:
    data = _load()
    data.setdefault("facts", {})[key.lower().strip()] = value.strip()
    _save(data)


def recall(key: str):
    return _load().get("facts", {}).get(key.lower().strip())


def log(role: str, text: str) -> None:
    data = _load()
    hist = data.setdefault("history", [])
    hist.append({"t": datetime.now().isoformat(timespec="seconds"), "role": role, "text": text})
    data["history"] = hist[-MAX_HISTORY:]
    _save(data)


def context_blob(request: str = "") -> str:
    """Compact context string handed to the LLM each request."""
    data = _load()
    facts = data.get("facts", {})
    lines = []
    if facts:
        lines.append("Known facts:")
        # Cap facts to keep planner fast.
        for i, (k, v) in enumerate(facts.items()):
            if i >= 12:
                break
            lines.append(f"- {k}: {v}")
    hist = data.get("history", [])[-4:]
    if hist:
        lines.append("Recent conversation:")
        lines += [f"- {h['role']}: {h['text']}" for h in hist]
    try:
        import app_learner
        learned = app_learner.knowledge_for_prompt(request)
        if learned:
            if len(learned) > 1200:
                learned = learned[:1200] + "\n…"
            lines.append(learned)
    except Exception:
        pass
    try:
        import pc_trainer
        inv = pc_trainer.inventory_for_prompt(request)
        if inv:
            if len(inv) > 900:
                inv = inv[:900] + "\n…"
            lines.append(inv)
    except Exception:
        pass
    try:
        import skills
        if request and any(w in request.lower() for w in (
            "youtube", "steam", "scroll", "fullscreen", "skip", "learn", "folder",
        )):
            lines.append("Prefer SKILL RECIPES for this request.")
    except Exception:
        pass
    return "\n".join(lines)
