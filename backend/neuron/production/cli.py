"""CLI entry: python -m neuron.production.cli install|audit|diagnostics|wizard."""

from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("Usage: python -m neuron.production.cli [install|audit|diagnostics|wizard|status] [preset]")
        return 2
    cmd = argv[0].lower()
    if str(Path_helper()) not in sys.path:
        sys.path.insert(0, str(Path_helper()))
    if cmd == "install":
        from neuron.production import installer
        print(json.dumps(installer.run_install(with_deps="--skip-deps" not in argv, shortcuts="--no-shortcuts" not in argv), indent=2))
        return 0
    if cmd == "audit":
        from neuron.production import audit
        print(json.dumps(audit.run_full_audit(), indent=2))
        return 0
    if cmd == "diagnostics":
        from neuron.production import diagnostics
        print(json.dumps(diagnostics.run_diagnostics(), indent=2))
        return 0
    if cmd == "wizard":
        from neuron.production import wizard
        preset = argv[1] if len(argv) > 1 else "balanced"
        print(json.dumps(wizard.apply_preset(preset), indent=2))
        return 0
    if cmd == "status":
        from neuron.production.orchestrator import dispatch
        from neuron.production.types import ProdCapability
        print(json.dumps(dispatch(ProdCapability.STATUS.value).to_dict(), indent=2))
        return 0
    print("Unknown command", cmd)
    return 2


def Path_helper():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    raise SystemExit(main())
