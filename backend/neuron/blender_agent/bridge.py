"""Bridge Blender Agent into agent.run (compose-only)."""

from __future__ import annotations

from typing import Any

from neuron.blender_agent.detect import looks_like_blender
from neuron.blender_agent.orchestrator import orchestrate


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("blender_agent", True))
    except Exception:
        return True


def maybe_handle_blender(
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
    if not looks_like_blender(text):
        return None
    try:
        return orchestrate(text, confirmed=confirmed)
    except Exception as exc:
        print(f"[blender_agent] bridge skipped: {exc}", flush=True)
        return None
