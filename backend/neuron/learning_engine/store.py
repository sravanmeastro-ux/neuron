"""Persistent store for learning engine state."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from neuron.learning_engine.types import ScoredItem

_LOCK = threading.Lock()
_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "learning_engine.json"

_EDITORS = {"code", "vscode", "visual studio code", "cursor", "notepad++", "sublime", "pycharm", "idea"}
_BROWSERS = {"chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi"}


class LearningStore:
    def __init__(self) -> None:
        self.items: dict[str, ScoredItem] = {}
        self.hour_hist: dict[str, dict[str, float]] = {}  # category|key -> hour -> weight
        self.weekday_hist: dict[str, dict[str, float]] = {}
        self.sequences: list[list[str]] = []  # recent tool name sequences
        self.hotkeys: dict[str, ScoredItem] = {}
        self.last_tools: list[str] = []
        self.updated_at: float = 0.0
        self._load()

    def _id(self, category: str, key: str) -> str:
        return f"{category}:{key.strip().lower()}"

    def get_or_create(self, category: str, key: str) -> ScoredItem:
        kid = self._id(category, key)
        if kid not in self.items:
            self.items[kid] = ScoredItem(key=key.strip(), category=category)
        return self.items[kid]

    def by_category(self, category: str) -> list[ScoredItem]:
        return [it for it in self.items.values() if it.category == category]

    def note_schedule(self, category: str, key: str, ts: float | None = None) -> None:
        ts = ts or time.time()
        lt = time.localtime(ts)
        hour = str(lt.tm_hour)
        wd = str(lt.tm_wday)
        ck = self._id(category, key)
        self.hour_hist.setdefault(ck, {})
        self.hour_hist[ck][hour] = self.hour_hist[ck].get(hour, 0.0) + 1.0
        self.weekday_hist.setdefault(ck, {})
        self.weekday_hist[ck][wd] = self.weekday_hist[ck].get(wd, 0.0) + 1.0

    def note_tool_sequence(self, tool: str) -> None:
        t = (tool or "").strip()
        if not t:
            return
        self.last_tools.append(t)
        self.last_tools = self.last_tools[-12:]
        if len(self.last_tools) >= 2:
            self.sequences.append(list(self.last_tools[-4:]))
            self.sequences = self.sequences[-200:]

    def save(self) -> None:
        with _LOCK:
            self.updated_at = time.time()
            data = {
                "items": {k: v.to_dict() for k, v in self.items.items()},
                "hour_hist": self.hour_hist,
                "weekday_hist": self.weekday_hist,
                "sequences": self.sequences[-200:],
                "hotkeys": {k: v.to_dict() for k, v in self.hotkeys.items()},
                "updated_at": self.updated_at,
            }
            try:
                _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
                _STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _load(self) -> None:
        try:
            if not _STORE_PATH.is_file():
                return
            data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
            for k, v in (data.get("items") or {}).items():
                self.items[k] = ScoredItem(
                    key=str(v.get("key") or ""),
                    category=str(v.get("category") or ""),
                    score=float(v.get("score") or 0),
                    count=int(v.get("count") or 0),
                    success=int(v.get("success") or 0),
                    fail=int(v.get("fail") or 0),
                    last_ts=float(v.get("last_ts") or 0),
                    meta=dict(v.get("meta") or {}),
                )
            self.hour_hist = dict(data.get("hour_hist") or {})
            self.weekday_hist = dict(data.get("weekday_hist") or {})
            self.sequences = list(data.get("sequences") or [])
            for k, v in (data.get("hotkeys") or {}).items():
                self.hotkeys[k] = ScoredItem(
                    key=str(v.get("key") or k),
                    category="hotkey",
                    score=float(v.get("score") or 0),
                    count=int(v.get("count") or 0),
                    success=int(v.get("success") or 0),
                    fail=int(v.get("fail") or 0),
                    last_ts=float(v.get("last_ts") or 0),
                )
            self.updated_at = float(data.get("updated_at") or 0)
        except Exception:
            pass

    def summary(self) -> dict[str, Any]:
        from neuron.learning_engine.scores import rank

        def top(cat: str, n: int = 5) -> list[dict]:
            return [
                {"key": it.key, "score": round(it.score, 3), "count": it.count}
                for it in rank(self.by_category(cat), limit=n)
            ]

        return {
            "apps": top("app"),
            "websites": top("website"),
            "browsers": top("browser"),
            "editors": top("editor"),
            "folders": top("folder"),
            "monitors": top("monitor"),
            "workflows": top("workflow"),
            "hotkeys": [
                {"key": it.key, "score": round(it.score, 3), "count": it.count}
                for it in rank(list(self.hotkeys.values()), limit=5)
            ],
            "updated_at": self.updated_at,
        }


_STORE: LearningStore | None = None


def get_store() -> LearningStore:
    global _STORE
    if _STORE is None:
        _STORE = LearningStore()
    return _STORE
