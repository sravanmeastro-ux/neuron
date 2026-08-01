"""Plugin installer — folder or zip → installed_root + load."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from neuron.plugin_market.paths import installed_root
from neuron.plugin_market import catalog as catalog_mod
from neuron.plugin_market import trust as trust_mod
from neuron.plugins.sdk import PluginManifest
from neuron.plugins.permissions import validate_manifest, check_dependencies
from neuron.plugins.loader import NEURON_VERSION, load_plugin, unload_plugin


def _read_manifest_dir(root: Path) -> PluginManifest:
    data = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    return PluginManifest.from_dict(data)


def install_from_dir(src: str | Path, *, overwrite: bool = True, grant_caps: list[str] | None = None) -> dict[str, Any]:
    src_p = Path(src).expanduser().resolve()
    if not src_p.is_dir() or not (src_p / "plugin.json").is_file():
        return {"ok": False, "error": f"Not a plugin directory: {src_p}"}
    man = _read_manifest_dir(src_p)
    errs = validate_manifest(man) + check_dependencies(man, neuron_version=NEURON_VERSION)
    # During install, plugin deps may not be loaded yet — soften missing plugin peers if discovered later
    hard = [e for e in errs if not e.startswith("Missing required plugin:")]
    if hard:
        return {"ok": False, "error": "; ".join(hard), "manifest": man.to_dict()}

    dest = installed_root() / man.id
    src_resolved = src_p.resolve()
    dest_resolved = dest.resolve() if dest.exists() else dest

    if dest.exists() and src_resolved == dest_resolved:
        # In-place update (same install root) — do not delete-then-copy
        loaded = load_plugin(dest, register=True)
        for cap in grant_caps or []:
            trust_mod.grant(man.id, cap)
        catalog_mod.upsert_catalog_entry({
            "id": man.id,
            "version": man.version,
            "name": man.name,
            "description": man.description,
            "source": "installed",
            "homepage": man.homepage,
            "path": str(dest),
        })
        return {
            "ok": bool(loaded.enabled),
            "plugin": loaded.to_dict(),
            "path": str(dest),
            "error": loaded.load_error,
            "inplace": True,
        }

    if dest.exists():
        if not overwrite:
            return {"ok": False, "error": f"Already installed: {man.id}"}
        unload_plugin(man.id)
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src_p, dest)
    loaded = load_plugin(dest, register=True)
    for cap in grant_caps or []:
        trust_mod.grant(man.id, cap)
    catalog_mod.upsert_catalog_entry({
        "id": man.id,
        "version": man.version,
        "name": man.name,
        "description": man.description,
        "source": "installed",
        "homepage": man.homepage,
        "path": str(dest),
    })
    return {
        "ok": bool(loaded.enabled),
        "plugin": loaded.to_dict(),
        "path": str(dest),
        "error": loaded.load_error,
    }


def install_from_zip(zip_path: str | Path, *, overwrite: bool = True) -> dict[str, Any]:
    zp = Path(zip_path).expanduser().resolve()
    if not zp.is_file():
        return {"ok": False, "error": f"Zip not found: {zp}"}
    staging = installed_root() / "_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zp, "r") as zf:
            zf.extractall(staging)
        # Find plugin.json (root or one level deep)
        candidates = list(staging.rglob("plugin.json"))
        if not candidates:
            return {"ok": False, "error": "Zip has no plugin.json"}
        root = candidates[0].parent
        return install_from_dir(root, overwrite=overwrite)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def uninstall(plugin_id: str) -> dict[str, Any]:
    pid = (plugin_id or "").strip()
    if not pid:
        return {"ok": False, "error": "Need plugin id"}
    unload_plugin(pid)
    dest = installed_root() / pid
    removed = False
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
        removed = True
    trust_mod.revoke(pid)
    return {"ok": True, "id": pid, "removed_files": removed}


def install_auto(source: str, **kwargs: Any) -> dict[str, Any]:
    p = Path(source).expanduser()
    if p.suffix.lower() == ".zip":
        return install_from_zip(p, **kwargs)
    return install_from_dir(p, **kwargs)
