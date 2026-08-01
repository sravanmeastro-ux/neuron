"""Bridge GitHub Agent into agent.run (compose-only)."""

from __future__ import annotations

from typing import Any

from neuron.github_agent.detect import looks_like_github
from neuron.github_agent.orchestrator import orchestrate


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("github_agent", True))
    except Exception:
        return True


def maybe_handle_github(
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
    if not looks_like_github(text):
        return None
    try:
        return orchestrate(text, confirmed=confirmed)
    except Exception as exc:
        print(f"[github_agent] bridge skipped: {exc}", flush=True)
        return None
