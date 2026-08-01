"""Short-term conversation memory for personality / continuity."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_TURNS: list[dict[str, Any]] = []
_MAX = 24
_PATH: Path | None = None


def _store() -> Path:
    global _PATH
    if _PATH is not None:
        return _PATH
    root = Path(__file__).resolve().parents[2] / "data"
    root.mkdir(parents=True, exist_ok=True)
    _PATH = root / "personality_conversation.json"
    return _PATH


def _load() -> None:
    global _TURNS
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        _TURNS = list(data.get("turns") or [])[-_MAX:]
    except Exception:
        _TURNS = []


def _save() -> None:
    try:
        _store().write_text(
            json.dumps({"turns": _TURNS[-_MAX:], "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def remember_turn(
    user: str,
    assistant: str,
    *,
    mode: str = "",
    emotion: str = "",
    path: str = "",
) -> None:
    with _LOCK:
        if not _TURNS:
            _load()
        _TURNS.append({
            "t": time.time(),
            "user": (user or "")[:500],
            "assistant": (assistant or "")[:500],
            "mode": mode,
            "emotion": emotion,
            "path": path,
        })
        _TURNS[:] = _TURNS[-_MAX:]
        _save()
    # Also mirror into session memory when available
    try:
        from neuron.memory.scopes import get_session
        sess = get_session()
        if user:
            sess.log("user", user)
        if assistant:
            sess.log("assistant", assistant)
    except Exception:
        pass


def recent(limit: int = 6) -> list[dict[str, Any]]:
    with _LOCK:
        if not _TURNS:
            _load()
        return list(_TURNS[-limit:])


def for_prompt(limit: int = 4) -> str:
    rows = recent(limit)
    if not rows:
        return ""
    lines = ["Recent conversation:"]
    for r in rows:
        if r.get("user"):
            lines.append(f"User: {r['user']}")
        if r.get("assistant"):
            lines.append(f"NEURON: {r['assistant']}")
    return "\n".join(lines)


def clear() -> None:
    with _LOCK:
        _TURNS.clear()
        _save()
