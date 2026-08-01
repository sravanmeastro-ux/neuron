"""Bridge Project Intelligence into agent.run (compose-only)."""

from __future__ import annotations

from typing import Any

from neuron.project_intelligence.detect import looks_like_project_intelligence
from neuron.project_intelligence.orchestrator import orchestrate


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("project_intelligence", True))
    except Exception:
        return True


def maybe_handle_project_intelligence(
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
    if not looks_like_project_intelligence(text):
        return None
    try:
        return orchestrate(text, confirmed=confirmed)
    except Exception as exc:
        print(f"[project_intelligence] bridge skipped: {exc}", flush=True)
        return None
