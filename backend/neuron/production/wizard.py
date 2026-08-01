"""Configuration wizard — release presets for settings."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

from neuron.production.paths import backend_root, wizard_state_path

PRESETS: dict[str, dict[str, Any]] = {
    "safe": {
        "label": "Safe / family",
        "logging": {"level": "WARNING"},
        "agent": {
            "strict_verify": True,
            "self_healing": True,
            "plugin_market": True,
            "multi_device": False,
        },
        "tts": {"enabled": True},
        "assistant": {"confirm_high_risk": True},
    },
    "balanced": {
        "label": "Balanced (recommended)",
        "logging": {"level": "INFO"},
        "agent": {
            "strict_verify": True,
            "self_healing": True,
            "plugin_market": True,
            "multi_device": True,
            "workflow_intelligence": True,
            "project_intelligence": True,
        },
        "tts": {"enabled": True},
    },
    "performance": {
        "label": "Performance",
        "logging": {"level": "WARNING"},
        "agent": {
            "strict_verify": True,
            "self_healing": True,
            "screen_verify": "off",
            "ocr_verify": "off",
        },
        "tts": {"enabled": True},
    },
    "developer": {
        "label": "Developer",
        "logging": {"level": "DEBUG"},
        "agent": {
            "strict_verify": True,
            "developer_mode": True,
            "github_agent": True,
            "plugin_market": True,
            "project_intelligence": True,
        },
    },
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def list_presets() -> list[dict[str, str]]:
    return [{"id": k, "label": v.get("label") or k} for k, v in PRESETS.items()]


def apply_preset(preset_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    pid = (preset_id or "balanced").lower().strip()
    if pid not in PRESETS:
        return {"ok": False, "error": f"Unknown preset: {preset_id}", "presets": list_presets()}
    path = backend_root() / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    overlay = {k: v for k, v in PRESETS[pid].items() if k != "label"}
    merged = _deep_merge(cfg, overlay)
    if dry_run:
        return {"ok": True, "dry_run": True, "preset": pid, "overlay": overlay}
    # backup
    bak = path.with_suffix(".json.bak")
    bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    state = {"preset": pid, "applied_at": time.time(), "backup": str(bak)}
    wizard_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"ok": True, "preset": pid, "label": PRESETS[pid]["label"], "backup": str(bak), "state": state}


def wizard_status() -> dict[str, Any]:
    path = wizard_state_path()
    state = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    return {"presets": list_presets(), "state": state}
