"""V4.9 LIVE procedure probe — DEFAULT dry-run / read-only.

Use --live only for explicit desktop actions (not enabled here by default).
Does not silently learn from live sessions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V4.9 procedure live probe")
    ap.add_argument("--live", action="store_true", help="Allow live desktop actions (OFF by default)")
    ap.add_argument("--goal", default="Do my YouTube search on monitor 1 for Rust tutorials")
    args = ap.parse_args(argv)

    from neuron.v4.learn import (
        get_procedure_registry,
        procedure_learning_enabled,
        learn_metrics,
        controls,
    )
    from neuron.v4.learn.execute import match_procedure_for_goal, expand_procedure_plan, extract_procedure_params
    from neuron.safety.policy import allow, risk_of

    print("V4.9 procedure LIVE probe")
    print(f"mode={'LIVE' if args.live else 'DRY-RUN/read-only'}")
    print(f"procedure_learning_enabled={procedure_learning_enabled()}")

    reg = get_procedure_registry()
    rows = controls.list_learned_procedures(limit=10)
    print(f"registry_count={len(rows)}")
    for r in rows[:5]:
        print(f"  - {r.get('procedure_id')} enabled={r.get('enabled')} conf={r.get('confidence')}")

    proc = match_procedure_for_goal(args.goal)
    if not proc:
        print("MATCH: none (dry-run ok — no learned procedure yet)")
        print("Would show planned expansion / safety / verification expectations when matched.")
        print(learn_metrics())
        if args.live:
            print("LIVE requested but no procedure matched — refusing silent actions.")
            return 0
        print("LIVE probe DRY-RUN PASS")
        return 0

    print(f"MATCH: {proc.procedure_id} v{proc.version}")
    params = extract_procedure_params(args.goal, proc)
    plan = expand_procedure_plan(proc, params)
    print("EXPANSION:")
    for s in plan["steps"]:
        tool = s.get("action")
        risk = risk_of(tool)
        ok, reason = allow(tool, s.get("args") or {}, confirmed=False)
        print(f"  - {tool} risk={risk} allow_unconfirmed={ok} verify=required")
        print(f"    reason={reason[:80]}")

    print("Safety: every future run re-classifies (old confirm != permanent auth)")
    print("Verification: intermediate + final required; executor ok != success")
    print("Recovery: RecoveryEngine remains active on FAILURE/UNCERTAIN")

    if not args.live:
        print("DRY-RUN complete - no desktop actions executed; learning not triggered.")
        print("LIVE probe DRY-RUN PASS")
        return 0

    print("LIVE mode: refusing automatic execution in this probe harness.")
    print("Use normal AgentLoop / run_procedure under operator control.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
