"""Persistent long-term memory store + value scoring."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

from neuron.memory_engine.types import MemoryItem, MemoryKind

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "long_term_memory.json"

# Auto-forget thresholds
MIN_VALUE_TO_KEEP = 0.25
MAX_ITEMS = 800
SUMMARY_AGE_DAYS = 3.0
SUMMARY_BATCH = 12


class LTMStore:
    def __init__(self) -> None:
        self.items: dict[str, MemoryItem] = {}
        self._load()

    def add(self, item: MemoryItem) -> MemoryItem:
        with _LOCK:
            self.items[item.item_id] = item
            self._save_unlocked()
        return item

    def get(self, item_id: str) -> MemoryItem | None:
        return self.items.get(item_id)

    def all(self, kind: str | None = None) -> list[MemoryItem]:
        items = list(self.items.values())
        if kind:
            items = [i for i in items if i.kind == kind]
        return items

    def touch(self, item: MemoryItem) -> None:
        item.access_count += 1
        item.last_access = time.time()
        item.value = min(5.0, float(item.value) + 0.15)
        item.updated_at = time.time()

    def pin(self, item: MemoryItem) -> None:
        item.pinned = True
        item.value = max(item.value, 3.0)
        item.updated_at = time.time()

    def effective_value(self, item: MemoryItem, *, now: float | None = None) -> float:
        now = now or time.time()
        if item.pinned:
            return 100.0 + float(item.value)
        age_days = max(0.0, (now - (item.last_access or item.created_at)) / 86400.0)
        decay = math.pow(0.5, age_days / 7.0)  # half-life 7 days
        access_boost = min(1.5, 0.1 * item.access_count)
        return float(item.value) * decay + access_boost

    def forget_low_value(self, *, now: float | None = None) -> list[str]:
        """Remove non-pinned low-value / excess memories. Returns deleted ids."""
        now = now or time.time()
        deleted: list[str] = []
        with _LOCK:
            ranked = sorted(
                self.items.values(),
                key=lambda i: self.effective_value(i, now=now),
                reverse=True,
            )
            keep: dict[str, MemoryItem] = {}
            for i, item in enumerate(ranked):
                if item.pinned:
                    keep[item.item_id] = item
                    continue
                if i >= MAX_ITEMS:
                    deleted.append(item.item_id)
                    continue
                if self.effective_value(item, now=now) < MIN_VALUE_TO_KEEP and item.access_count == 0:
                    # Only if older than 2 days
                    if (now - item.created_at) > 2 * 86400:
                        deleted.append(item.item_id)
                        continue
                keep[item.item_id] = item
            self.items = keep
            self._save_unlocked()
        return deleted

    def summarize_old(self, *, now: float | None = None) -> MemoryItem | None:
        """Compact old episodic/conversation items into one semantic summary."""
        now = now or time.time()
        cutoff = now - SUMMARY_AGE_DAYS * 86400
        with _LOCK:
            candidates = [
                i
                for i in self.items.values()
                if not i.pinned
                and i.kind in (MemoryKind.EPISODIC.value, MemoryKind.CONVERSATION.value)
                and i.created_at < cutoff
                and not i.summary_of
            ]
            candidates.sort(key=lambda i: i.created_at)
            batch = candidates[:SUMMARY_BATCH]
            if len(batch) < 3:
                return None
            lines = []
            ids = []
            for it in batch:
                lines.append(f"- [{time.strftime('%Y-%m-%d', time.localtime(it.created_at))}] {it.content[:160]}")
                ids.append(it.item_id)
            summary = MemoryItem(
                kind=MemoryKind.SEMANTIC.value,
                title="Memory summary",
                content="Summarized older memories:\n" + "\n".join(lines)[:1500],
                value=1.5,
                tags=["summary", "auto"],
                summary_of=ids,
                meta={"count": len(ids)},
            )
            for iid in ids:
                self.items.pop(iid, None)
            self.items[summary.item_id] = summary
            self._save_unlocked()
            return summary

    def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        q = (query or "").lower().strip()
        tokens = [t for t in q.split() if len(t) > 1]
        now = time.time()
        scored: list[tuple[float, MemoryItem]] = []
        for item in self.all(kind):
            if since and item.created_at < since:
                continue
            if until and item.created_at > until:
                continue
            blob = f"{item.title} {item.content} {' '.join(item.tags)}".lower()
            hit = 0.0
            if not tokens:
                hit = 0.1
            else:
                for t in tokens:
                    if t in blob:
                        hit += 1.0
            if hit <= 0 and tokens:
                continue
            self.touch(item)
            scored.append((hit + 0.1 * self.effective_value(item, now=now), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        with _LOCK:
            self._save_unlocked()
        return [i for _, i in scored[:limit]]

    def _save_unlocked(self) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {"items": {k: v.to_dict() for k, v in self.items.items()}}
            _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load(self) -> None:
        try:
            if not _PATH.is_file():
                return
            data = json.loads(_PATH.read_text(encoding="utf-8"))
            for k, v in (data.get("items") or {}).items():
                self.items[k] = MemoryItem.from_dict(v)
        except Exception:
            pass

    def stats(self) -> dict[str, Any]:
        by: dict[str, int] = {}
        for i in self.items.values():
            by[i.kind] = by.get(i.kind, 0) + 1
        return {"total": len(self.items), "by_kind": by, "pinned": sum(1 for i in self.items.values() if i.pinned)}


_STORE: LTMStore | None = None


def get_store() -> LTMStore:
    global _STORE
    if _STORE is None:
        _STORE = LTMStore()
    return _STORE
