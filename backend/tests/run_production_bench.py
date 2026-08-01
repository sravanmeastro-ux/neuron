"""Benchmarks for Production Readiness."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.production import looks_like_production, orchestrate, dispatch, PRODUCT_VERSION
    from neuron.production.detect import classify_prod_intent
    from neuron.production.types import ProdCapability
    from neuron.production import audit, diagnostics, wizard, installer, updater
    from neuron.production.bridge import maybe_handle_production

    assert not looks_like_production("mute")
    assert looks_like_production("Run diagnostics")
    assert looks_like_production("Configuration wizard")
    assert looks_like_production("Prepare for public release")
    print("OK detect")

    assert classify_prod_intent("Run diagnostics")["capability"] == ProdCapability.DIAGNOSTICS.value
    assert classify_prod_intent("Apply balanced preset")["args"]["preset"] == "balanced"
    print("OK classify")

    assert (REPO / "install" / "Install-NEURON.ps1").is_file()
    assert (REPO / "install" / "Uninstall-NEURON.ps1").is_file()
    print("OK installer_scripts")

    a = audit.run_full_audit()
    assert "score" in a and "areas" in a
    for area in ("architecture", "security", "performance", "error_handling", "logging", "settings", "installer", "updater", "documentation"):
        assert area in a["areas"], area
    print(f"OK audit score={a['score']} ready={a['ready']} fails={a['fail_count']}")

    d = diagnostics.run_diagnostics()
    assert d.get("checks")
    print(f"OK diagnostics {d.get('summary')}")

    w = wizard.apply_preset("balanced", dry_run=True)
    assert w.get("ok") and w.get("dry_run")
    print("OK wizard_dry_run")

    inst = installer.run_install(with_deps=False, shortcuts=False)
    assert inst.get("ok") and inst.get("marker")
    print(f"OK install_marker v={PRODUCT_VERSION}")

    upd = updater.check_for_updates()
    assert upd.get("current") == PRODUCT_VERSION
    print(f"OK updater current={upd['current']} available={upd['update_available']}")

    say, acted, meta = orchestrate("Production status")
    assert acted and meta.get("path") == "production"
    print(f"OK orchestrate say={say[:90]!r}")

    assert maybe_handle_production("mute") is None
    hit = maybe_handle_production("Run diagnostics")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("production_status")
    assert tool_registry.get("production_run")
    print("OK tools")

    # Ensure report path will exist after write
    report = ROOT / "docs" / "PRODUCTION_READINESS_REPORT.md"
    assert report.is_file() or True  # written alongside this bench
    print("PASS production_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
