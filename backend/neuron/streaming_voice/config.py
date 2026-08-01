"""Streaming voice config helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CFG = Path(__file__).resolve().parent.parent.parent / "config.json"


def voice_cfg() -> dict[str, Any]:
    try:
        return json.loads(_CFG.read_text(encoding="utf-8")).get("voice", {}) or {}
    except Exception:
        return {}


def streaming_enabled() -> bool:
    return bool(voice_cfg().get("streaming_voice_engine", True))


def listen_mode_default() -> str:
    return str(voice_cfg().get("listen_mode", "continuous") or "continuous").lower()


def early_intent_enabled() -> bool:
    return bool(voice_cfg().get("early_intent_enabled", True))


def streaming_tts_enabled() -> bool:
    try:
        tts = json.loads(_CFG.read_text(encoding="utf-8")).get("tts", {}) or {}
        return bool(tts.get("streaming", True)) and bool(voice_cfg().get("streaming_tts_ws", True))
    except Exception:
        return True


def echo_cancellation_enabled() -> bool:
    return bool(voice_cfg().get("echo_cancellation", True))


def noise_suppression_enabled() -> bool:
    return bool(voice_cfg().get("noise_suppression", True))


def barge_in_level() -> float:
    return float(voice_cfg().get("barge_in_level", 0.25) or 0.25)
