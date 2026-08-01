"""Plugin Market orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.plugin_market import catalog, hot_reload, installer, scaffold, trust, updater
from neuron.plugin_market.api import HOST_API_VERSION, api_docs
from neuron.plugin_market.detect import classify_market_intent
from neuron.plugin_market.types import MarketCapability, MarketResult
from neuron.plugins import loader, manager


def dispatch(capability: str, args: dict[str, Any] | None = None) -> MarketResult:
    args = args or {}

    if capability == MarketCapability.STATUS.value:
        plugs = loader.list_plugins()
        watch = hot_reload.status()
        updates = updater.check_updates()
        say = (
            f"Plugin Market online (Host API {HOST_API_VERSION}). "
            f"Loaded={len(plugs)}; updates={updates.get('count', 0)}; "
            f"hot_reload={'on' if watch.get('running') else 'off'}."
        )
        return MarketResult(
            ok=True,
            say=say,
            capability=capability,
            data={"plugins": plugs, "watch": watch, "updates": updates, "api": api_docs()},
        )

    if capability == MarketCapability.LIST.value:
        plugs = loader.list_plugins()
        names = ", ".join(f"{p.get('id')}@{p.get('version')}" for p in plugs[:12])
        return MarketResult(ok=True, say=f"{len(plugs)} plugins: {names}.", capability=capability, data={"plugins": plugs})

    if capability == MarketCapability.CATALOG.value:
        cat = catalog.load_catalog()
        n = len(cat.get("plugins") or [])
        return MarketResult(ok=True, say=f"Catalog has {n} entries.", capability=capability, data=cat)

    if capability == MarketCapability.INSTALL.value:
        source = str(args.get("source") or args.get("path") or "").strip()
        if not source:
            return MarketResult(ok=False, error="Need plugin path/zip", say="Need install source path.", capability=capability)
        r = installer.install_auto(source, overwrite=bool(args.get("overwrite", True)))
        return MarketResult(
            ok=bool(r.get("ok")),
            say=f"Installed {((r.get('plugin') or {}).get('id'))}." if r.get("ok") else (r.get("error") or "Install failed"),
            acted=bool(r.get("ok")),
            capability=capability,
            data=r,
            error=str(r.get("error") or ""),
        )

    if capability == MarketCapability.UNINSTALL.value:
        pid = str(args.get("id") or "").strip()
        if not pid:
            return MarketResult(ok=False, error="Need plugin id", say="Need plugin id.", capability=capability)
        r = installer.uninstall(pid)
        return MarketResult(ok=True, say=f"Uninstalled {pid}.", acted=True, capability=capability, data=r)

    if capability == MarketCapability.UPDATE.value:
        pid = str(args.get("id") or "").strip()
        if not pid:
            return MarketResult(ok=False, error="Need plugin id", say="Need plugin id.", capability=capability)
        r = updater.update_plugin(pid, package_path=args.get("package_path"))
        return MarketResult(
            ok=bool(r.get("ok")),
            say=r.get("say") or (f"Updated {pid}." if r.get("ok") else r.get("error") or "Update failed"),
            acted=bool(r.get("ok")),
            capability=capability,
            data=r,
            error=str(r.get("error") or ""),
        )

    if capability == MarketCapability.UPDATE_ALL.value:
        r = updater.update_all()
        n = len(r.get("results") or [])
        return MarketResult(ok=bool(r.get("ok")), say=f"Update pass complete ({n} attempted).", acted=True, capability=capability, data=r)

    if capability == MarketCapability.HOT_RELOAD.value:
        r = hot_reload.reload_all()
        return MarketResult(ok=True, say=f"Hot-reloaded {r.get('count', 0)} plugins.", acted=True, capability=capability, data=r)

    if capability == MarketCapability.WATCH_START.value:
        r = hot_reload.start_watch(interval_s=float(args.get("interval_s") or 1.5))
        return MarketResult(ok=True, say=r.get("say") or "Watcher started.", acted=True, capability=capability, data=r)

    if capability == MarketCapability.WATCH_STOP.value:
        r = hot_reload.stop_watch()
        return MarketResult(ok=True, say=r.get("say") or "Watcher stopped.", acted=True, capability=capability, data=r)

    if capability == MarketCapability.SCAFFOLD.value:
        pid = str(args.get("id") or "demo").strip()
        r = scaffold.scaffold(pid, name=str(args.get("name") or ""), description=str(args.get("description") or ""))
        if not r.get("ok"):
            return MarketResult(ok=False, error=r.get("error") or "scaffold failed", say=r.get("error") or "scaffold failed", capability=capability)
        return MarketResult(
            ok=True,
            say=f"Scaffolded plugin {pid} at {r.get('path')}.",
            acted=True,
            capability=capability,
            data=r,
        )

    if capability == MarketCapability.TRUST.value:
        pid = str(args.get("id") or "").strip()
        cap = str(args.get("capability") or "filesystem").strip()
        if not pid:
            return MarketResult(ok=False, say="Need plugin id for grant.", capability=capability)
        r = trust.grant(pid, cap)
        return MarketResult(
            ok=bool(r.get("ok")),
            say=f"Granted {cap} to {pid}." if r.get("ok") else (r.get("error") or "grant failed"),
            acted=bool(r.get("ok")),
            capability=capability,
            data={"grant": r, "all": trust.list_grants()},
            error=str(r.get("error") or ""),
        )

    return MarketResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False) -> tuple[str, bool, dict]:
    intent = classify_market_intent(text)
    cap = intent.get("capability") or MarketCapability.STATUS.value
    args = dict(intent.get("args") or {})
    result = dispatch(cap, args)
    meta = {
        "path": "plugin_market",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Plugin market failed.", True, meta
