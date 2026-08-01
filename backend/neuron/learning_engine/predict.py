"""Habit prediction from schedule histograms + ranked favorites."""

from __future__ import annotations

import time
from typing import Any

from neuron.learning_engine.scores import decayed_score, rank
from neuron.learning_engine.store import get_store


def predict_next(*, now: float | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """
    Predict likely next habits given current hour/weekday.
    Combines schedule affinity with decayed reinforcement score.
    """
    now = now or time.time()
    lt = time.localtime(now)
    hour = str(lt.tm_hour)
    wd = str(lt.tm_wday)
    store = get_store()
    scored: list[tuple[float, dict]] = []

    for item in store.items.values():
        if item.category in ("utterance",):
            continue
        kid = f"{item.category}:{item.key.strip().lower()}"
        h = (store.hour_hist.get(kid) or {}).get(hour, 0.0)
        w = (store.weekday_hist.get(kid) or {}).get(wd, 0.0)
        sched = h + 0.5 * w
        base = decayed_score(item, now=now)
        # Need some evidence
        if item.count < 1 and sched <= 0:
            continue
        pred = base * 0.6 + min(3.0, sched) * 0.4
        if pred <= 0 and item.count < 2:
            continue
        scored.append((
            pred,
            {
                "category": item.category,
                "key": item.key,
                "score": round(base, 3),
                "schedule_affinity": round(sched, 2),
                "prediction": round(pred, 3),
                "count": item.count,
            },
        ))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in scored[:limit]]


def predict_app(*, now: float | None = None) -> str | None:
    preds = [p for p in predict_next(now=now, limit=10) if p["category"] == "app"]
    return preds[0]["key"] if preds else None


def predict_workflow(*, now: float | None = None) -> str | None:
    store = get_store()
    flows = rank(store.by_category("workflow"), limit=3, now=now)
    return flows[0].key if flows else None


def coding_habits_summary() -> dict[str, Any]:
    store = get_store()
    editors = rank(store.by_category("editor"), limit=3)
    coding_utt = [i for i in store.by_category("utterance") if i.key == "coding"]
    hotkeys = rank(list(store.hotkeys.values()), limit=5)
    return {
        "preferred_editor": editors[0].key if editors else "",
        "editors": [{"key": e.key, "score": round(e.score, 3), "count": e.count} for e in editors],
        "coding_commands": coding_utt[0].count if coding_utt else 0,
        "hotkeys": [{"key": h.key, "count": h.count} for h in hotkeys],
    }
