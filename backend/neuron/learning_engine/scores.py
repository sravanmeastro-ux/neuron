"""Reinforcement scoring — EWMA + time decay ranking."""

from __future__ import annotations

import math
import time

from neuron.learning_engine.types import (
    ALPHA_FAIL,
    ALPHA_SUCCESS,
    DECAY_HALF_LIFE_DAYS,
    REWARD_FAIL,
    REWARD_SUCCESS,
    ScoredItem,
)


def reinforce(item: ScoredItem, *, ok: bool, now: float | None = None) -> ScoredItem:
    """Update score with success/fail reward (EWMA)."""
    now = now or time.time()
    reward = REWARD_SUCCESS if ok else REWARD_FAIL
    alpha = ALPHA_SUCCESS if ok else ALPHA_FAIL
    item.score = (1.0 - alpha) * float(item.score) + alpha * reward
    item.count += 1
    if ok:
        item.success += 1
    else:
        item.fail += 1
    item.last_ts = now
    return item


def decayed_score(item: ScoredItem, *, now: float | None = None) -> float:
    """Time-decayed score for ranking (half-life days)."""
    now = now or time.time()
    if not item.last_ts:
        return float(item.score)
    days = max(0.0, (now - item.last_ts) / 86400.0)
    # score * 0.5^(days/half_life)
    factor = math.pow(0.5, days / max(0.1, DECAY_HALF_LIFE_DAYS))
    # Slight boost for high success ratio
    ratio = item.success / max(1, item.count)
    return float(item.score) * factor * (0.7 + 0.3 * ratio)


def rank(items: list[ScoredItem], *, limit: int = 10, now: float | None = None) -> list[ScoredItem]:
    now = now or time.time()
    return sorted(items, key=lambda it: decayed_score(it, now=now), reverse=True)[:limit]
