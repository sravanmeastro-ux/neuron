"""App-level updater — version check + release notes (local-first)."""

from __future__ import annotations

import json
import time
from typing import Any

from neuron.production.paths import PRODUCT_VERSION, data_dir, release_notes_path
from neuron.plugins.permissions import compare_versions


def current_version() -> str:
    return PRODUCT_VERSION


def load_channel() -> dict[str, Any]:
    path = data_dir() / "update_channel.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    channel = {
        "latest": PRODUCT_VERSION,
        "channel": "stable",
        "notes": f"NEURON {PRODUCT_VERSION} public release candidate channel.",
        "updated": time.time(),
    }
    path.write_text(json.dumps(channel, indent=2), encoding="utf-8")
    return channel


def check_for_updates() -> dict[str, Any]:
    ch = load_channel()
    latest = str(ch.get("latest") or PRODUCT_VERSION)
    cmp = compare_versions(latest, PRODUCT_VERSION)
    return {
        "ok": True,
        "current": PRODUCT_VERSION,
        "latest": latest,
        "update_available": cmp > 0,
        "channel": ch.get("channel"),
        "notes": ch.get("notes"),
    }


def apply_local_update_marker(new_version: str) -> dict[str, Any]:
    """Record that an update package was applied (actual files delivered by installer)."""
    ch = load_channel()
    ch["latest"] = new_version
    ch["updated"] = time.time()
    (data_dir() / "update_channel.json").write_text(json.dumps(ch, indent=2), encoding="utf-8")
    notes = (
        f"# NEURON {new_version}\n\n"
        f"Updated from {PRODUCT_VERSION} at {time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
        f"Re-run install/Install-NEURON.ps1 after pulling release artifacts.\n"
    )
    release_notes_path().write_text(notes, encoding="utf-8")
    return {"ok": True, "notes_path": str(release_notes_path()), "channel": ch}
