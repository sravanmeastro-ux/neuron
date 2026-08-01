"""V4.10 voice soak — DEFAULT dry-run. --live required. Bounded tasks.

Usage:
  python tests/run_v4_voice_soak.py
  python tests/run_v4_voice_soak.py --live --max-tasks 10 --max-seconds 180
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

POOL = [
    "Open Chrome",
    "Focus Chrome",
    "Move Chrome to monitor 2",
    "Maximize Chrome",
    "Search YouTube for Blender tutorials",
    "Open Notepad",
    "Focus Notepad",
    "Move Chrome to monitor 1",
    "Go to YouTube",
    "Open Chrome",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="V4.10 voice soak")
    ap.add_argument("--live", action="store_true", help="Allow desktop mutation (OFF by default)")
    ap.add_argument("--max-tasks", type=int, default=5)
    ap.add_argument("--max-seconds", type=float, default=60.0)
    args = ap.parse_args(argv)

    from neuron.v4.voice import (
        plan_hierarchical_readonly,
        canary_eligible,
        infer_intent_family,
        procedure_learning_off,
        voice_metrics,
        reset_voice_metrics,
        voice_config_snapshot,
    )

    reset_voice_metrics()
    assert procedure_learning_off()
    print("V4.10 voice soak")
    print(f"mode={'LIVE' if args.live else 'DRY-RUN'} max_tasks={args.max_tasks} max_seconds={args.max_seconds}")
    print("config=", voice_config_snapshot())

    t_end = time.time() + float(args.max_seconds)
    attempts = 0
    rows = []

    if not args.live:
        for utt in POOL[: max(1, args.max_tasks)]:
            if time.time() > t_end:
                break
            attempts += 1
            tools, _, _ = plan_hierarchical_readonly(utt)
            fam = infer_intent_family(utt)
            elig, reason = canary_eligible(text=utt, intent_family=fam, tools=tools)
            print(f"  [{attempts}] PLAN {utt!r} eligible={elig} tools={tools[:3]}")
        print({
            "attempts": attempts,
            "soak_status": "NOT_RUN",
            **voice_metrics(),
        })
        print("soak results: NOT_RUN")
        print("PASS voice soak dry-run")
        return 0

    snap = voice_config_snapshot()
    if not snap.get("hierarchical_voice_enabled") or snap.get("voice_routing_mode") not in ("CANARY", "HIERARCHICAL"):
        print("BLOCKED: need hierarchical_voice_enabled + CANARY for LIVE soak")
        return 2

    from v4_voice_live_support import run_live_utterance, summarize_results, LIVE_POOL

    pool = LIVE_POOL[: max(1, int(args.max_tasks))]
    for utt in pool:
        if time.time() > t_end:
            print("max-seconds reached — stopping")
            break
        attempts += 1
        print(f"  [{attempts}] EXEC {utt!r} ...")
        r = run_live_utterance(utt)
        rows.append(r)
        print(f"    outcome={r['outcome']} path={r['path']} ms={r['elapsed_ms']}")
        m = voice_metrics()
        if m.get("VOICE_DUPLICATE_EXECUTION_COUNT", 0) > 0 or m.get("VOICE_SAFETY_MISMATCH_COUNT", 0) > 0:
            print("STOP soak: safety/duplicate metric raised")
            break

    summary = summarize_results(rows)
    out = {
        "soak_status": "PASS" if rows else "FAIL",
        "summary": summary,
        "results": rows,
        "metrics": voice_metrics(),
        "config": voice_config_snapshot(),
    }
    out_path = Path(__file__).resolve().parent / "v4_voice_soak_results.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("SUMMARY:", summary)
    print("WROTE", out_path)
    print("PASS voice soak LIVE" if rows else "FAIL empty soak")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
