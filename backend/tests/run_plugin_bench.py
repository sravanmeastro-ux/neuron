"""Benchmarks for Plugin SDK — discover, load, intents, hot reload."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED = {
    "chrome",
    "blender",
    "photoshop",
    "discord",
    "steam",
    "obs",
    "spotify",
    "office",
    "vscode",
    "cursor",
}


def main() -> int:
    from neuron.plugins import loader, manager
    from neuron.plugins.permissions import satisfies, validate_manifest
    from neuron.plugins.sdk import PluginManifest

    roots = loader.discover()
    ids = set()
    for root in roots:
        m = loader._read_manifest(root)
        ids.add(m.id)
        errs = validate_manifest(m)
        assert not errs, f"{m.id}: {errs}"
    missing = EXPECTED - ids
    assert not missing, f"Missing plugins: {missing}"
    print(f"OK discover n={len(roots)} ids={sorted(ids)}")

    assert satisfies(">=4.0", "4.10.0")
    assert not satisfies(">=5.0", "4.10.0")
    print("OK semver")

    # Fresh load via manager (may already be in registry from prior imports)
    loaded = manager.bootstrap()
    enabled = [p for p in loaded if p.get("enabled")]
    assert len(enabled) >= len(EXPECTED), f"enabled={len(enabled)} loaded={loaded}"
    print(f"OK load enabled={len(enabled)}/{len(loaded)}")

    intents = loader.intents_index()
    assert len(intents) >= len(EXPECTED)
    chrome_intents = [i for i in intents if i["plugin"] == "chrome"]
    assert chrome_intents, "chrome intents missing"
    print(f"OK intents n={len(intents)}")

    docs = manager.docs("chrome")
    assert "Chrome" in docs or "chrome" in docs.lower()
    print(f"OK docs chrome chars={len(docs)}")

    rel = manager.reload("chrome")
    assert rel.get("ok"), rel
    print("OK hot_reload chrome")

    listed = manager.list_plugins()
    assert any(p["id"] == "chrome" for p in listed)
    print(f"OK list n={len(listed)}")

    # Tool registry surface
    from neuron.brain import tool_registry

    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("plugins_list")
    assert tool_registry.get("plugin_reload")
    assert tool_registry.get("plugin_docs")
    assert tool_registry.get("chrome.open") or tool_registry.get("chrome_open")
    print("OK tool_registry plugins_list / chrome.open")

    # Manifest round-trip
    sample = PluginManifest.from_dict(
        {
            "id": "demo",
            "version": "1.2.3",
            "actions": [{"name": "demo.ping", "handler": "actions:ping", "risk": "safe"}],
            "intents": [{"id": "demo.ping", "aliases": ["ping demo"], "prefer": ["demo.ping"]}],
            "permissions": {"risk_ceiling": "safe"},
            "dependencies": {"neuron": ">=4.0", "tools": []},
        }
    )
    assert sample.version == "1.2.3"
    assert sample.to_dict()["id"] == "demo"
    print("OK manifest roundtrip")

    print("PASS plugin_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
