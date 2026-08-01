"""Bridge Computer Use Agent into agent.run (additive)."""

from __future__ import annotations

from typing import Any

from neuron.computer_use.detect import looks_like_computer_use
from neuron.computer_use.agent import handle


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("computer_use_agent", True))
    except Exception:
        return True


def maybe_handle_computer_use(
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
    # Confirm resume for pending CU
    low = text.lower().strip()
    if low in ("confirm", "yes", "go ahead", "do it", "proceed") and confirmed:
        # Caller may pass confirmed=True from brain confirm path; still need pending
        pass
    if not looks_like_computer_use(text) and low not in ("confirm", "yes", "go ahead", "proceed"):
        return None
    # Don't steal bare confirm — only CU goals
    if not looks_like_computer_use(text):
        return None
    try:
        return handle(text, loop=loop, confirmed=confirmed)
    except Exception as exc:
        print(f"[computer_use] bridge skipped: {exc}", flush=True)
        return None
