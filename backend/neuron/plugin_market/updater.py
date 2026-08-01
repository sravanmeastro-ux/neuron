"""Plugin updater — bump from catalog or local newer package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neuron.plugin_market import catalog as catalog_mod
from neuron.plugin_market.installer import install_from_dir
from neuron.plugin_market.paths import installed_root
from neuron.plugins import loader
from neuron.plugins.permissions import compare_versions


def check_updates() -> dict[str, Any]:
    installed = loader.list_plugins()
    plans = catalog_mod.plan_updates(installed)
    return {"ok": True, "updates": plans, "count": len(plans)}


def update_plugin(plugin_id: str, *, package_path: str | None = None) -> dict[str, Any]:
    """Update one plugin from an explicit package path or catalog metadata bump."""
    pid = (plugin_id or "").strip()
    if not pid:
        return {"ok": False, "error": "Need plugin id"}

    if package_path:
        return install_from_dir(package_path, overwrite=True)

    cat = catalog_mod.find_catalog(pid)
    if not cat:
        return {"ok": False, "error": f"No catalog entry for {pid}"}

    # If catalog points at a path with newer package, install it (unless path is the install itself)
    path = cat.get("path")
    if path and Path(path).is_dir():
        dest = installed_root() / pid
        if Path(path).resolve() == dest.resolve():
            # Same folder — bump manifest version then reload
            pj = dest / "plugin.json"
            data = json.loads(pj.read_text(encoding="utf-8"))
            cur = str(data.get("version") or "0.0.0")
            latest = str(cat.get("version") or cur)
            if compare_versions(latest, cur) <= 0:
                return {"ok": True, "skipped": True, "id": pid, "version": cur, "say": "Already up to date"}
            data["version"] = latest
            pj.write_text(json.dumps(data, indent=2), encoding="utf-8")
            from neuron.plugins import manager
            return {"ok": True, "id": pid, "version": latest, "reload": manager.reload(pid)}
        return install_from_dir(path, overwrite=True)

    # Builtin / catalog-only: rewrite installed copy version marker if present,
    # else report no local package (market would fetch remotely in future).
    dest = installed_root() / pid
    if dest.is_dir() and (dest / "plugin.json").is_file():
        data = json.loads((dest / "plugin.json").read_text(encoding="utf-8"))
        cur = str(data.get("version") or "0.0.0")
        latest = str(cat.get("version") or cur)
        if compare_versions(latest, cur) <= 0:
            return {"ok": True, "skipped": True, "id": pid, "version": cur, "say": "Already up to date"}
        data["version"] = latest
        (dest / "plugin.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        from neuron.plugins import manager
        return {"ok": True, "id": pid, "version": latest, "reload": manager.reload(pid)}

    # For builtins: hot-reload is enough when catalog says same source
    if cat.get("source") == "builtin":
        from neuron.plugins import manager
        return {"ok": True, "id": pid, "say": "Builtin — reloaded from disk", "reload": manager.reload(pid)}

    return {"ok": False, "error": f"No installable package for {pid}; provide package_path"}


def update_all() -> dict[str, Any]:
    plan = check_updates()
    results = []
    for u in plan.get("updates") or []:
        results.append(update_plugin(str(u["id"])))
    ok = all(r.get("ok") for r in results) if results else True
    return {"ok": ok, "results": results, "planned": plan.get("updates") or []}


def bump_catalog_version(plugin_id: str, new_version: str) -> dict[str, Any]:
    """Dev helper: mark a newer catalog version to exercise updater."""
    entry = catalog_mod.find_catalog(plugin_id) or {"id": plugin_id, "source": "installed"}
    entry["version"] = new_version
    catalog_mod.upsert_catalog_entry(entry)
    return entry
