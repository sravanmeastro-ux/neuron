"""Bridge Self-Healing into agent.run (compose-only)."""

from __future__ import annotations

from typing import Any

from neuron.self_healing.detect import looks_like_self_healing
from neuron.self_healing.orchestrator import orchestrate


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("self_healing", True))
    except Exception:
        return True


def maybe_handle_self_healing(
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
    if not looks_like_self_healing(text):
        return None
    try:
        # Keep main-loop heartbeat fresh when voice path hits us
        try:
            from neuron.self_healing.watchdog import tick_main_heartbeat
            tick_main_heartbeat()
        except Exception:
            pass
        return orchestrate(text, confirmed=confirmed)
    except Exception as exc:
        print(f"[self_healing] bridge skipped: {exc}", flush=True)
        return None
