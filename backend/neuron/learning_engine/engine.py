"""Learning Engine public API — rank, predict, prompt context."""

from __future__ import annotations

from typing import Any

from neuron.learning_engine.observe import observe_tool, observe_utterance
from neuron.learning_engine.predict import coding_habits_summary, predict_app, predict_next, predict_workflow
from neuron.learning_engine.scores import rank
from neuron.learning_engine.store import get_store


def favorites(category: str, *, limit: int = 5) -> list[dict[str, Any]]:
    store = get_store()
    items = rank(store.by_category(category), limit=limit)
    return [
        {
            "key": it.key,
            "score": round(it.score, 3),
            "count": it.count,
            "success": it.success,
            "fail": it.fail,
        }
        for it in items
    ]


def ranked_behaviors(*, limit: int = 15) -> list[dict[str, Any]]:
    store = get_store()
    all_items = list(store.items.values()) + list(store.hotkeys.values())
    return [
        {
            "category": it.category,
            "key": it.key,
            "score": round(it.score, 3),
            "count": it.count,
        }
        for it in rank(all_items, limit=limit)
    ]


def for_prompt(*, limit: int = 4) -> str:
    """Compact personalization blob for planners / LLM context."""
    store = get_store()
    s = store.summary()
    preds = predict_next(limit=3)
    lines = ["[learning_engine]"]
    if s.get("apps"):
        lines.append("favorite_apps: " + ", ".join(x["key"] for x in s["apps"][:limit]))
    if s.get("websites"):
        lines.append("favorite_sites: " + ", ".join(x["key"] for x in s["websites"][:limit]))
    if s.get("browsers"):
        lines.append("preferred_browser: " + s["browsers"][0]["key"])
    if s.get("editors"):
        lines.append("preferred_editor: " + s["editors"][0]["key"])
    if s.get("folders"):
        lines.append("frequent_folders: " + ", ".join(x["key"] for x in s["folders"][:limit]))
    if s.get("monitors"):
        lines.append("monitor_prefs: " + ", ".join(x["key"] for x in s["monitors"][:limit]))
    if s.get("workflows"):
        lines.append("workflows: " + "; ".join(x["key"] for x in s["workflows"][:3]))
    if s.get("hotkeys"):
        lines.append("hotkeys: " + ", ".join(x["key"] for x in s["hotkeys"][:limit]))
    if preds:
        lines.append(
            "predict_now: "
            + ", ".join(f"{p['category']}:{p['key']}" for p in preds)
        )
    code = coding_habits_summary()
    if code.get("preferred_editor"):
        lines.append(f"coding_editor: {code['preferred_editor']}")
    return "\n".join(lines) if len(lines) > 1 else ""


def snapshot() -> dict[str, Any]:
    return {
        "summary": get_store().summary(),
        "predictions": predict_next(limit=5),
        "coding": coding_habits_summary(),
        "ranked": ranked_behaviors(limit=12),
        "predict_app": predict_app(),
        "predict_workflow": predict_workflow(),
    }


def tool_learning_status(args: dict | None = None) -> Any:
    from neuron.windows.result import ok
    return ok("Learning engine status.", state=snapshot(), method="learning_engine")
