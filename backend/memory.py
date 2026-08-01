"""N.E.U.R.O.N long-term memory — JSON + SQLite (Phase 5).

Keeps facts/preferences across sessions and a rolling recent-history log.
SQLite is primary for facts/history/tool_runs; JSON remains compatible mirror.
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


def remember(key: str, value: str, *, force: bool = False) -> str:
    """Write a durable fact via PersistentMemory (allowlisted unless force=True)."""
    try:
        from neuron.memory import scopes
        ok, msg = scopes.persistent().remember(key, value, force=force)
        return msg if ok else msg
    except Exception:
        # Fallback: legacy direct write
        data = _load()
        data.setdefault("facts", {})[key.lower().strip()] = value.strip()
        _save(data)
        try:
            from neuron.memory import store as sql
            sql.remember(key, value)
        except Exception:
            pass
        return f"Remembered {key}."


def recall(key: str):
    try:
        from neuron.memory import scopes
        val = scopes.persistent().recall(key)
        if val is not None:
            return val
    except Exception:
        pass
    try:
        from neuron.memory import store as sql
        val = sql.recall(key)
        if val is not None:
            return val
    except Exception:
        pass
    return _load().get("facts", {}).get(key.lower().strip())


def forget(key: str) -> str:
    try:
        from neuron.memory import scopes
        _ok, msg = scopes.persistent().forget(key)
        return msg
    except Exception as exc:
        return str(exc)


def log(role: str, text: str) -> None:
    # Session scope (this run)
    try:
        from neuron.memory import scopes
        scopes.session().log(role, text)
    except Exception:
        pass
    data = _load()
    hist = data.setdefault("history", [])
    hist.append({"t": datetime.now().isoformat(timespec="seconds"), "role": role, "text": text})
    data["history"] = hist[-MAX_HISTORY:]
    _save(data)
    try:
        from neuron.memory import store as sql
        sql.ensure()
        conn = sql._conn()
        conn.execute(
            "INSERT INTO history(t,role,text) VALUES(?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), role, text),
        )
        conn.execute(
            "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 40)"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def context_blob(request: str = "") -> str:
    """Compact context string handed to the LLM each request.

    Prefers scoped Working / Session / Persistent blobs, then legacy extras.
    """
    lines: list[str] = []
    try:
        from neuron.memory import scopes
        scoped = scopes.context_blob(request)
        if scoped:
            lines.append(scoped)
    except Exception:
        pass

    # Legacy durable facts only if scopes did not already emit PERSISTENT_MEMORY
    if not any(l.startswith("PERSISTENT_MEMORY:") for chunk in lines for l in chunk.splitlines()):
        data = _load()
        facts = data.get("facts", {})
        try:
            from neuron.memory import store as sql
            sql.ensure()
            conn = sql._conn()
            rows = conn.execute("SELECT key, value FROM facts LIMIT 12").fetchall()
            conn.close()
            if rows:
                facts = {r["key"]: r["value"] for r in rows}
        except Exception:
            pass
        if facts:
            lines.append("Known facts:")
            for i, (k, v) in enumerate(facts.items()):
                if i >= 12:
                    break
                lines.append(f"- {k}: {v}")
        # Session chat already in SESSION_MEMORY; keep JSON history only if session empty
        try:
            from neuron.memory import scopes
            sess_empty = not scopes.session().conversation
        except Exception:
            sess_empty = True
        if sess_empty:
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
        import voice_recipes
        recipes = voice_recipes.for_prompt(18)
        if recipes:
            if len(recipes) > 900:
                recipes = recipes[:900] + "\n…"
            lines.append(recipes)
    except Exception:
        pass
    try:
        import priority_apps
        pmap = priority_apps.for_prompt(request)
        if pmap:
            if len(pmap) > 700:
                pmap = pmap[:700] + "\n…"
            lines.append(pmap)
    except Exception:
        pass
    try:
        from neuron.memory.store import recent_tool_runs
        runs = recent_tool_runs(4)
        if runs:
            lines.append("Recent tool runs:\n" + "\n".join(runs))
    except Exception:
        pass
    try:
        from neuron.learning_engine import for_prompt as learning_for_prompt
        blob = learning_for_prompt()
        if blob:
            lines.append(blob)
    except Exception:
        pass
    try:
        from neuron.memory_engine import for_prompt as ltm_for_prompt
        blob = ltm_for_prompt()
        if blob:
            lines.append(blob)
    except Exception:
        pass
    try:
        import skills
        if request and any(w in request.lower() for w in (
            "youtube", "steam", "discord", "friends", "scroll", "fullscreen",
            "skip", "learn", "folder", "settings", "whatsapp", "blender", "opera",
        )):
            lines.append("Prefer SKILL RECIPES for this request.")
    except Exception:
        pass
    return "\n".join(lines)
