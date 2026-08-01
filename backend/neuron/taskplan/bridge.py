"""Bridge Task Planning Engine into agent.run (does not touch FastIntent/Screen/Semantic)."""

from __future__ import annotations

from typing import Any

from neuron.taskplan.detect import looks_like_workflow, is_cancel_command, is_resume_command, is_confirm_command
from neuron.taskplan.engine import handle


def _enabled() -> bool:
    try:
        import json
        from pathlib import Path
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("task_planning_engine", True))
    except Exception:
        return True


def maybe_handle_taskplan(
    raw: str,
    *,
    normalized: str = "",
    loop: Any | None = None,
    confirmed: bool = False,
) -> tuple[str | None, bool, dict] | None:
    """
    Opt-in multi-step workflow handler.
    Returns (say, acted, meta) or None to fall through to CapabilityRouter / AgentLoop.
    """
    if not _enabled():
        return None
    text = (normalized or raw or "").strip()
    if not text:
        return None
    # Always allow cancel/resume/confirm when a task may be active
    if not (
        looks_like_workflow(text)
        or is_cancel_command(text)
        or is_resume_command(text)
        or is_confirm_command(text)
    ):
        return None
    try:
        return handle(text, loop=loop, confirmed=confirmed)
    except Exception as exc:
        print(f"[taskplan] bridge skipped: {exc}", flush=True)
        return None
