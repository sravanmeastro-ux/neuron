"""V4.10 LIVE voice probe — DEFAULT dry-run. Explicit --live for desktop actions.

Usage:
  python tests/run_v4_voice_live.py
  python tests/run_v4_voice_live.py --live --max-tasks 3
  python tests/run_v4_voice_live.py --live --multi-turn
  python tests/run_v4_voice_live.py --live --max-tasks 20
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

SAFE_SCENARIOS = [
    "Open Chrome",
    "Focus Chrome",
    "Move Chrome to monitor 2",
    "Maximize Chrome",
    "Go to YouTube",
    "Search YouTube for Blender tutorials",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description="V4.10 voice LIVE probe")
    ap.add_argument("--live", action="store_true", help="Allow desktop mutation (OFF by default)")
    ap.add_argument("--multi-turn", action="store_true", help="Run multi-turn LIVE sequence when --live")
    ap.add_argument("--max-tasks", type=int, default=3, help="Max LIVE utterances (default 3)")
    ap.add_argument("--correction", action="store_true", help="Run correction scenario when --live")
    ap.add_argument("--cancel", action="store_true", help="Run cancel/stop scenario when --live")
    ap.add_argument("--confirm", action="store_true", help="Run confirmation scenario when --live")
    args = ap.parse_args(argv)

    from neuron.v4.voice import (
        voice_config_snapshot,
        plan_hierarchical_readonly,
        canary_eligible,
        infer_intent_family,
        procedure_learning_off,
        voice_metrics,
        reset_voice_metrics,
    )
    from v4_voice_live_support import (
        LIVE_POOL,
        run_live_utterance,
        summarize_results,
    )

    reset_voice_metrics()
    print("V4.10 voice LIVE probe")
    print("mode=", "LIVE" if args.live else "DRY-RUN")
    print("config=", voice_config_snapshot())
    assert procedure_learning_off(), "procedure_learning must be OFF"

    # Always show plan preview (no mutation)
    preview = []
    for utt in SAFE_SCENARIOS:
        t0 = time.perf_counter()
        tools, intent, meta = plan_hierarchical_readonly(utt)
        fam = infer_intent_family(utt)
        elig, reason = canary_eligible(text=utt, intent_family=fam, tools=tools)
        row = {
            "utterance": utt,
            "tools": tools[:4],
            "eligible": elig,
            "reason": reason,
            "plan_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        preview.append(row)
        print(f"  PLAN {utt!r} tools={tools[:3]} eligible={elig}")

    if not args.live:
        print("LIVE results: NOT_RUN (dry-run only; pass --live to mutate)")
        print("PASS voice live dry-run")
        return 0

    # LIVE mutation path
    snap = voice_config_snapshot()
    if not snap.get("hierarchical_voice_enabled"):
        print("BLOCKED: hierarchical_voice_enabled must be true for LIVE canary execution")
        return 2
    mode = str(snap.get("voice_routing_mode") or "")
    if mode not in ("CANARY", "HIERARCHICAL"):
        print(f"BLOCKED: voice_routing_mode={mode} (need CANARY for LIVE execute)")
        return 2

    rows: list[dict] = []
    n = max(1, int(args.max_tasks))

    if args.multi_turn:
        sequence = [
            "Open Chrome on monitor 2",
            "Go to YouTube",
            "Search Blender tutorials",
            "Play the first one",
            "Make it fullscreen",
            "Pause it",
            "Move it to monitor 1",
        ]
        print("MULTI-TURN LIVE:")
        for utt in sequence[:n]:
            print(f"  EXEC {utt!r} ...")
            r = run_live_utterance(utt)
            rows.append(r)
            print(f"    path={r['path']} outcome={r['outcome']} ms={r['elapsed_ms']} recovered={r['recovered']}")
            if r["outcome"] == "WAITING_FOR_CONFIRMATION":
                print("    (pending confirm — stopping multi-turn)")
                break
    elif args.correction:
        print("CORRECTION LIVE:")
        for utt in ["Open Chrome on monitor 2", "Actually put it on monitor 1"][:n]:
            print(f"  EXEC {utt!r} ...")
            r = run_live_utterance(utt)
            rows.append(r)
            print(f"    path={r['path']} outcome={r['outcome']} ms={r['elapsed_ms']}")
    elif args.cancel:
        print("CANCEL LIVE:")
        from neuron.speech import interrupt as interrupt_mod
        print("  EXEC Open Chrome ...")
        r1 = run_live_utterance("Open Chrome")
        rows.append(r1)
        interrupt_mod.request(reason="neuron_stop_test")
        print("  INTERRUPT Neuron stop via brain")
        r2 = run_live_utterance("Neuron stop", via_brain=True)
        rows.append(r2)
        interrupt_mod.clear()
        print(f"    stop say={r2.get('say')!r} outcome={r2.get('outcome')}")
    elif args.confirm:
        print("CONFIRM LIVE (safe controlled via brain.handle_command):")
        from neuron.safety.policy import requires_confirm
        probe = "Close Notepad"
        _ = requires_confirm("close_app", {"name": "Notepad"})
        r1 = run_live_utterance(probe, via_brain=True)
        rows.append(r1)
        print(f"  first outcome={r1['outcome']} needs_confirm={bool(r1.get('needs_confirm'))} say={r1['say'][:80]!r}")
        if r1["outcome"] == "WAITING_FOR_CONFIRMATION" or r1.get("needs_confirm") or "confirm" in (r1.get("say") or "").lower():
            r_yes = run_live_utterance("yes", via_brain=True)
            rows.append(r_yes)
            print(f"  yes -> {r_yes['outcome']} say={r_yes['say'][:100]!r}")
            # Unrelated while nothing pending should not authorize old action
            r_unrel = run_live_utterance("Open Spotify", via_brain=True)
            rows.append(r_unrel)
            print(f"  unrelated -> {r_unrel['outcome']}")
        else:
            print("  No confirmation pending from probe — marking confirm UX BLOCKED/N/A for this policy")
    else:
        tasks = LIVE_POOL[:n]
        print(f"LIVE executing {len(tasks)} tasks:")
        for utt in tasks:
            print(f"  EXEC {utt!r} ...")
            r = run_live_utterance(utt)
            rows.append(r)
            print(
                f"    path={r['path']} hier={r['hierarchical_voice']} "
                f"outcome={r['outcome']} ms={r['elapsed_ms']} recovered={r['recovered']}"
            )
            # Hard stop on safety/duplicate signals
            from neuron.v4.voice import voice_metrics
            m = voice_metrics()
            if m.get("VOICE_DUPLICATE_EXECUTION_COUNT", 0) > 0:
                print("STOP: VOICE_DUPLICATE_EXECUTION_COUNT > 0")
                break
            if m.get("VOICE_SAFETY_MISMATCH_COUNT", 0) > 0:
                print("STOP: VOICE_SAFETY_MISMATCH_COUNT > 0")
                break

    summary = summarize_results(rows)
    metrics = voice_metrics()
    out = {
        "preview": preview,
        "results": rows,
        "summary": summary,
        "metrics": metrics,
        "config": voice_config_snapshot(),
    }
    out_path = Path(__file__).resolve().parent / "v4_voice_live_results.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("SUMMARY:", summary)
    print("METRICS:", metrics)
    print("WROTE", out_path)

    # Gate: no duplicate / safety / unverified completion
    assert metrics.get("VOICE_DUPLICATE_EXECUTION_COUNT", 0) == 0
    assert metrics.get("VOICE_SAFETY_MISMATCH_COUNT", 0) == 0
    assert metrics.get("UNVERIFIED_COMPLETION_RESPONSE_COUNT", 0) == 0
    print("PASS voice live probe")
    return 0


if __name__ == "__main__":
    # Allow `python tests/run_v4_voice_live.py` import of tests.v4_voice_live_support
    tests_dir = Path(__file__).resolve().parent
    if str(tests_dir.parent) not in sys.path:
        sys.path.insert(0, str(tests_dir.parent))
    raise SystemExit(main())
