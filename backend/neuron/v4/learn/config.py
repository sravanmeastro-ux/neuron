"""Learning config — central enable/disable (default preserves teach-only behavior)."""

from __future__ import annotations

from typing import Any


def procedure_learning_enabled() -> bool:
    """Default False — do not auto-learn from every verified success."""
    try:
        import json
        from pathlib import Path
        cfg_path = Path(__file__).resolve().parents[3] / "config.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        agent = data.get("agent") or {}
        if "procedure_learning_enabled" in agent:
            return bool(agent["procedure_learning_enabled"])
        learn = data.get("learning") or {}
        if "procedure_learning_enabled" in learn:
            return bool(learn["procedure_learning_enabled"])
    except Exception:
        pass
    return False


def learning_config() -> dict[str, Any]:
    return {
        "procedure_learning_enabled": procedure_learning_enabled(),
        "min_evidence_for_auto_accept": 3,
        "min_steps_for_procedure": 2,
    }


__all__ = ["procedure_learning_enabled", "learning_config"]
