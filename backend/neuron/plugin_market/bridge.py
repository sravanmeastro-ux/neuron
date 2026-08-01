"""Bridge Plugin Market into agent.run (compose-only)."""

from __future__ import annotations

from typing import Any

from neuron.plugin_market.detect import looks_like_plugin_market
from neuron.plugin_market.orchestrator import orchestrate


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        agent = cfg.get("agent") or {}
        if agent.get("plugin_market") is False:
            return False
        return bool(agent.get("plugin_sdk", True) or agent.get("plugin_market", True))
    except Exception:
        return True


def maybe_handle_plugin_market(
    raw: str,
    *,
    normalized: str = "",
    loop: Any | None = None,
    confirmed: bool = False,
) -> tuple[str | None, bool, dict] | None:
    if not _enabled():
        return None
    text = (normalized or raw or "").strip()
    if not text:
        return None
    if not looks_like_plugin_market(text):
        return None
    try:
        return orchestrate(text, confirmed=confirmed)
    except Exception as exc:
        print(f"[plugin_market] bridge skipped: {exc}", flush=True)
        return None
