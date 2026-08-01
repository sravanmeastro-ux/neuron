"""Bridge multi-agent Coordinator into agent.run (additive)."""

from __future__ import annotations

from typing import Any

from neuron.agents.coordinator import _enabled, handle, looks_like_multi_agent


def maybe_handle_multi_agent(
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
    if not looks_like_multi_agent(text):
        return None
    # Never steal bare confirm / cancel
    low = text.lower().strip()
    if low in ("confirm", "yes", "cancel", "stop", "undo", "mute", "unmute"):
        return None
    try:
        return handle(text, loop=loop, confirmed=confirmed)
    except Exception as exc:
        print(f"[multi_agent] bridge skipped: {exc}", flush=True)
        return None
