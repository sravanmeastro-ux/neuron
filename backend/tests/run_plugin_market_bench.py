"""Benchmarks for Plugin Market / production SDK."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.plugin_market import looks_like_plugin_market, orchestrate, dispatch, get_api
    from neuron.plugin_market.detect import classify_market_intent
    from neuron.plugin_market.types import MarketCapability
    from neuron.plugin_market import scaffold, installer, updater, hot_reload, catalog, trust
    from neuron.plugin_market.bridge import maybe_handle_plugin_market
    from neuron.plugins.permissions import compare_versions

    assert not looks_like_plugin_market("mute")
    assert not looks_like_plugin_market("Open Chrome")
    assert looks_like_plugin_market("Install plugin")
    assert looks_like_plugin_market("Update plugins")
    assert looks_like_plugin_market("Hot reload plugins")
    assert looks_like_plugin_market("Scaffold a plugin demo")
    print("OK detect")

    assert classify_market_intent("Update plugins")["capability"] == MarketCapability.UPDATE_ALL.value
    assert classify_market_intent("Scaffold a plugin demo")["args"]["id"] == "demo"
    print("OK classify")

    assert compare_versions("1.2.0", "1.1.9") > 0
    assert compare_versions("1.0.0", "1.0.0") == 0
    print("OK versioning")

    api = get_api()
    assert api.version
    assert "call_tool" in api_docs_text()
    print(f"OK plugin_api v={api.version}")

    sc = scaffold.scaffold("marketbench", description="Bench scaffold")
    assert sc.get("ok") and Path(sc["path"]).joinpath("plugin.json").is_file()
    print(f"OK scaffold path={sc['path']}")

    inst = installer.install_from_dir(sc["path"], overwrite=True)
    assert inst.get("ok"), inst
    assert (inst.get("plugin") or {}).get("id") == "marketbench"
    print("OK install")

    trust.grant("marketbench", "filesystem")
    assert trust.is_granted("marketbench", "filesystem")
    print("OK permissions/trust")

    catalog.load_catalog()
    updater.bump_catalog_version("marketbench", "0.2.0")
    plans = updater.check_updates()
    assert any(u.get("id") == "marketbench" for u in (plans.get("updates") or []))
    print(f"OK updater plans={plans.get('count')}")

    upd = updater.update_plugin("marketbench")
    assert upd.get("ok"), upd
    print(f"OK update -> {upd.get('version') or upd}")

    hr = hot_reload.reload_all()
    assert hr.get("ok")
    print(f"OK hot_reload count={hr.get('count')}")

    w = hot_reload.start_watch(interval_s=0.4)
    assert w.get("ok")
    time.sleep(0.9)
    # touch actions to trigger reload
    actions = Path(sc["path"]) / "actions.py"
    # installed copy
    from neuron.plugin_market.paths import installed_root
    inst_actions = installed_root() / "marketbench" / "actions.py"
    if inst_actions.is_file():
        txt = inst_actions.read_text(encoding="utf-8")
        inst_actions.write_text(txt + "\n# touch\n", encoding="utf-8")
    time.sleep(1.0)
    st = hot_reload.status()
    assert st.get("running") and st.get("ticks", 0) >= 1
    hot_reload.stop_watch()
    print(f"OK watcher ticks={st.get('ticks')} reloads={st.get('reloads')}")

    un = installer.uninstall("marketbench")
    assert un.get("ok")
    print("OK uninstall")

    say, acted, meta = orchestrate("Plugin market status")
    assert acted and meta.get("path") == "plugin_market"
    print(f"OK orchestrate say={say[:90]!r}")

    assert maybe_handle_plugin_market("mute") is None
    hit = maybe_handle_plugin_market("Plugin catalog")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("plugin_market_status")
    assert tool_registry.get("plugin_market_run")
    print("OK tools")

    print("PASS plugin_market_bench")
    return 0


def api_docs_text() -> str:
    from neuron.plugin_market.api import api_docs
    return api_docs()


if __name__ == "__main__":
    raise SystemExit(main())
