"""Learning engine config."""

from __future__ import annotations

import json
from pathlib import Path


def enabled() -> bool:
    try:
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        )
        return bool((cfg.get("agent") or {}).get("learning_engine", True))
    except Exception:
        return True
