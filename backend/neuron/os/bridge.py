"""Bridge NEURON OS into agent.run (additive, Category A safe)."""

from __future__ import annotations

from typing import Any

from neuron.os.detect import looks_like_os_shell
from neuron.os.orchestrator import orchestrate


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("neuron_os", True))
    except Exception:
        return True


def maybe_handle_os(
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
    if not looks_like_os_shell(text):
        return None
    try:
        return orchestrate(text, confirmed=confirmed, loop=loop)
    except Exception as exc:
        print(f"[neuron_os] bridge skipped: {exc}", flush=True)
        return None
