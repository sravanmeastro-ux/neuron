"""Voice routing config — fail closed to LEGACY."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neuron.v4.voice.types import VoiceRoutingMode

_CFG_PATH = Path(__file__).resolve().parents[3] / "config.json"


def _agent_cfg() -> dict[str, Any]:
    try:
        data = json.loads(_CFG_PATH.read_text(encoding="utf-8"))
        return dict(data.get("agent") or {})
    except Exception:
        return {}


def hierarchical_voice_enabled() -> bool:
    return bool(_agent_cfg().get("hierarchical_voice_enabled", False))


def voice_routing_mode() -> VoiceRoutingMode:
    """Invalid / disallowed configs fail closed to LEGACY."""
    raw = str(_agent_cfg().get("voice_routing_mode") or "LEGACY").strip().upper()
    try:
        mode = VoiceRoutingMode(raw)
    except Exception:
        return VoiceRoutingMode.LEGACY
    if mode is VoiceRoutingMode.LEGACY:
        return mode
    # Master flag required for SHADOW/CANARY/HIERARCHICAL
    if not hierarchical_voice_enabled():
        return VoiceRoutingMode.LEGACY
    return mode


def procedure_learning_off() -> bool:
    try:
        from neuron.v4.learn.config import procedure_learning_enabled
        return not procedure_learning_enabled()
    except Exception:
        return True


def voice_config_snapshot() -> dict[str, Any]:
    return {
        "hierarchical_voice_enabled": hierarchical_voice_enabled(),
        "voice_routing_mode": voice_routing_mode().value,
        "configured_mode": str(_agent_cfg().get("voice_routing_mode") or "LEGACY"),
        "procedure_learning_enabled": not procedure_learning_off(),
    }


__all__ = [
    "hierarchical_voice_enabled",
    "voice_routing_mode",
    "procedure_learning_off",
    "voice_config_snapshot",
]
