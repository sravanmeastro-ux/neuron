"""Local plugin catalog + SemVer update planning."""

from __future__ import annotations

import json
import time
from typing import Any

from neuron.plugin_market.paths import catalog_path
from neuron.plugins.permissions import compare_versions


def default_catalog() -> dict[str, Any]:
    """Seed catalog entries mirroring builtins (for updater demos)."""
    builtins = [
        ("chrome", "1.0.0", "Browser control"),
        ("blender", "1.0.0", "Blender launcher"),
        ("photoshop", "1.0.0", "Photoshop launcher"),
        ("discord", "1.0.0", "Discord launcher"),
        ("steam", "1.0.0", "Steam launcher"),
        ("obs", "1.0.0", "OBS launcher"),
        ("spotify", "1.0.0", "Spotify launcher"),
        ("office", "1.0.0", "Office launchers"),
        ("vscode", "1.0.0", "VS Code launcher"),
        ("cursor", "1.0.0", "Cursor launcher"),
    ]
    return {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "api_version": "1",
        "plugins": [
            {
                "id": pid,
                "version": ver,
                "name": pid.title(),
                "description": desc,
                "source": "builtin",
                "homepage": "",
            }
            for pid, ver, desc in builtins
        ],
    }


def load_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.is_file():
        cat = default_catalog()
        save_catalog(cat)
        return cat
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_catalog()


def save_catalog(data: dict[str, Any]) -> Path:
    data = dict(data)
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = catalog_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def upsert_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    cat = load_catalog()
    plugins = list(cat.get("plugins") or [])
    pid = str(entry.get("id") or "")
    plugins = [p for p in plugins if str(p.get("id")) != pid]
    plugins.append(entry)
    cat["plugins"] = plugins
    save_catalog(cat)
    return entry


def find_catalog(plugin_id: str) -> dict[str, Any] | None:
    for p in load_catalog().get("plugins") or []:
        if str(p.get("id")) == plugin_id:
            return p
    return None


def plan_updates(installed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare installed versions to catalog; return upgrade candidates."""
    out = []
    for inst in installed:
        pid = str(inst.get("id") or "")
        cur = str(inst.get("version") or "0.0.0")
        cat = find_catalog(pid)
        if not cat:
            continue
        latest = str(cat.get("version") or cur)
        if compare_versions(latest, cur) > 0:
            out.append({
                "id": pid,
                "current": cur,
                "latest": latest,
                "source": cat.get("source"),
                "description": cat.get("description"),
            })
    return out
