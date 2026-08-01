"""Sync channel collectors / appliers for memory, tasks, voice, plugins, projects."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from neuron.multi_device.identity import backend_root, sync_snapshot_dir
from neuron.multi_device.types import SyncChannel


def _safe_read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def channel_sources() -> dict[str, list[Path]]:
    root = backend_root()
    return {
        SyncChannel.MEMORY.value: [
            root / "data" / "long_term_memory.json",
            root / "memory_store.json",
        ],
        SyncChannel.TASKS.value: [
            root / "data" / "taskplan_state.json",
        ],
        SyncChannel.VOICE.value: [
            root / "voice_recipes.json",
            root / "config.json",  # voice/tts slices only when packing
        ],
        SyncChannel.PLUGINS.value: [
            root / "data" / "plugins" / "catalog.json",
            root / "data" / "plugins" / "trust.json",
        ],
        SyncChannel.PROJECTS.value: [
            root / "data" / "project_intelligence",
        ],
    }


def collect_channel(channel: str) -> dict[str, Any]:
    root = backend_root()
    files: dict[str, Any] = {}
    meta: dict[str, Any] = {"channel": channel, "collected_at": time.time()}

    if channel == SyncChannel.VOICE.value:
        cfg = _safe_read_json(root / "config.json") or {}
        files["voice_config"] = {
            "voice": cfg.get("voice"),
            "tts": cfg.get("tts"),
            "assistant": {
                k: (cfg.get("assistant") or {}).get(k)
                for k in ("mode", "voice", "tts_enabled", "stt_enabled")
                if (cfg.get("assistant") or {}).get(k) is not None
            },
        }
        recipes = _safe_read_json(root / "voice_recipes.json")
        if recipes is not None:
            files["voice_recipes.json"] = recipes
        return {"ok": True, "meta": meta, "files": files}

    if channel == SyncChannel.PROJECTS.value:
        pdir = root / "data" / "project_intelligence"
        payload = {}
        if pdir.is_dir():
            for p in pdir.glob("*.json"):
                payload[p.name] = _safe_read_json(p)
        files["project_intelligence"] = payload
        return {"ok": True, "meta": meta, "files": files}

    for path in channel_sources().get(channel, []):
        if path.is_dir():
            continue
        if path.name == "config.json":
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        data = _safe_read_json(path)
        if data is not None:
            files[rel] = data
        elif path.is_file():
            files[rel] = {"_raw": path.read_text(encoding="utf-8", errors="replace")[:200_000]}
    return {"ok": True, "meta": meta, "files": files}


def write_snapshot(device_id: str, channel: str, payload: dict[str, Any] | None = None) -> Path:
    payload = payload or collect_channel(channel)
    out = sync_snapshot_dir(device_id) / f"{channel}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def read_snapshot(device_id: str, channel: str) -> dict[str, Any] | None:
    path = sync_snapshot_dir(device_id) / f"{channel}.json"
    return _safe_read_json(path)


def apply_channel(channel: str, payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Apply a sync payload onto the local host (merge-friendly)."""
    root = backend_root()
    files = (payload or {}).get("files") or {}
    applied: list[str] = []
    skipped: list[str] = []

    if channel == SyncChannel.VOICE.value:
        if dry_run:
            return {"ok": True, "dry_run": True, "would_apply": list(files.keys())}
        # Merge voice slices into a sidecar (do not clobber full config blindly)
        side = root / "data" / "multi_device" / "synced_voice.json"
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps(files, indent=2), encoding="utf-8")
        if "voice_recipes.json" in files:
            recipes_path = root / "voice_recipes.json"
            if not dry_run:
                # backup then write
                if recipes_path.is_file():
                    shutil.copy2(recipes_path, recipes_path.with_suffix(".json.bak"))
                recipes_path.write_text(json.dumps(files["voice_recipes.json"], indent=2), encoding="utf-8")
            applied.append("voice_recipes.json")
        applied.append("synced_voice.json")
        return {"ok": True, "applied": applied, "skipped": skipped}

    if channel == SyncChannel.PROJECTS.value:
        bundle = files.get("project_intelligence") or {}
        pdir = root / "data" / "project_intelligence"
        if not dry_run:
            pdir.mkdir(parents=True, exist_ok=True)
            for name, content in bundle.items():
                if content is None:
                    continue
                (pdir / name).write_text(json.dumps(content, indent=2), encoding="utf-8")
                applied.append(name)
        else:
            applied = list(bundle.keys())
        return {"ok": True, "applied": applied, "dry_run": dry_run}

    for rel, content in files.items():
        path = root / rel
        if dry_run:
            applied.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        if isinstance(content, dict) and "_raw" in content and len(content) == 1:
            path.write_text(str(content["_raw"]), encoding="utf-8")
        else:
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        applied.append(rel)
    return {"ok": True, "applied": applied, "skipped": skipped, "dry_run": dry_run}


ALL_CHANNELS = [c.value for c in SyncChannel]
