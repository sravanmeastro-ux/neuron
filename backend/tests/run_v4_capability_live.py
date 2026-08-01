"""V4.8 LIVE capability probe — DEFAULT dry-run / read-only.

Requires --live for any mutating action (never used by regression).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="Allow live mutations (unsafe)")
    p.add_argument("--execute", action="store_true", help="With --live, execute one safe open/focus")
    args = p.parse_args(argv)

    from neuron.v4.capability import reset_capability_catalog, coverage_report, resolve_intent

    print("V4.8 capability LIVE probe")
    print("mode:", "LIVE" if args.live else "DRY-RUN (default)")
    cat = reset_capability_catalog()
    rep = coverage_report()
    print(f"registered={rep['total']} shared={len(rep['shared'])} legacy_only={rep['LEGACY_ONLY_CAPABILITY_COUNT']}")

    # Read-only world peek
    try:
        from neuron.v3.context_engine import get_engine
        obs = get_engine().refresh_observation("")
        print("world peek keys:", list(obs.keys())[:8] if isinstance(obs, dict) else type(obs))
    except Exception as exc:
        print("world peek skipped:", exc)

    plan = resolve_intent("focus_app", {"name": "Notepad"})
    print("planned focus_app ->", plan.tool, "risk=", plan.risk)

    if args.execute:
        if not args.live:
            print("Refusing execute without --live")
            return 2
        print("LIVE execute not enabled in default probe harness (safe stop).")
        return 0

    print("DRY-RUN complete (no desktop mutations).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
