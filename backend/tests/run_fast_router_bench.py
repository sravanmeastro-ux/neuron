"""Benchmark FastIntentRouter vs AgentLoop for deterministic desktop commands.

Usage (from backend/):
  python tests/run_fast_router_bench.py
  python tests/run_fast_router_bench.py --live

Asserts Category A commands do NOT use AgentLoop on the fast path.
Writes: tests/fast_router_bench_report.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAFE = [
    "volume up",
    "volume down",
    "mute",
    "undo",
    "copy",
    "paste",
]

LIVE = [
    "open notepad",
    "open chrome",
]


def _bench_fast(text: str) -> dict:
    from neuron.brain.fast_router import classify, try_handle

    d = classify(text)
    t0 = time.perf_counter()
    fr = try_handle(text)
    ms = (time.perf_counter() - t0) * 1000.0
    return {
        "utt": text,
        "path": "fast_router",
        "ms": round(ms, 2),
        "ok": bool(fr and fr.ok),
        "used_agent_loop": bool(fr.used_agent_loop) if fr else None,
        "category": d.category,
        "confidence": d.confidence,
        "band": d.band,
        "capability": d.capability_id,
        "say": (fr.say if fr else None),
    }


def _bench_agent_loop_forced(text: str) -> dict:
    """Old architecture: CapabilityRouter plan → AgentLoop (bypass fast)."""
    from neuron.brain.agent_loop import AgentLoop
    from neuron.brain.normalize import normalize_plan
    from neuron.v3 import capability_router as cap_mod

    routed = cap_mod.route(text)
    if not (routed.ok and routed.steps):
        return {"utt": text, "path": "agent_loop", "ms": None, "ok": False, "error": "no_route"}

    plan = normalize_plan(routed.as_plan() or {"say": "", "steps": list(routed.steps)})
    # Soft open wait for fairer compare when live
    for step in plan.get("steps") or []:
        if (step.get("action") or step.get("tool")) == "open_app":
            args = step.setdefault("args", step.get("arguments") or {})
            if isinstance(args, dict):
                args.setdefault("wait_seconds", 3)

    loop = AgentLoop(confirmed=False)
    t0 = time.perf_counter()
    say, acted, loop_meta, goal = loop.run(
        request=text,
        context="",
        normalized=text,
        plan=plan,
        observe_blob="bench_forced_agent_loop",
        confirmed=False,
    )
    ms = (time.perf_counter() - t0) * 1000.0
    return {
        "utt": text,
        "path": "agent_loop",
        "ms": round(ms, 2),
        "ok": bool(acted),
        "used_agent_loop": True,
        "say": (say or "")[:120],
        "status": getattr(goal, "status", None),
    }


def _stats(rows: list[dict]) -> dict:
    vals = [r["ms"] for r in rows if isinstance(r.get("ms"), (int, float))]
    if not vals:
        return {}
    vals_sorted = sorted(vals)
    p95_idx = max(0, int(round(0.95 * (len(vals_sorted) - 1))))
    return {
        "n": len(vals),
        "mean_ms": round(statistics.mean(vals), 2),
        "median_ms": round(statistics.median(vals), 2),
        "p95_ms": round(vals_sorted[p95_idx], 2),
        "worst_ms": round(max(vals), 2),
        "best_ms": round(min(vals), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--compare-agent", action="store_true", help="Also time forced AgentLoop")
    args = ap.parse_args()

    utts = list(SAFE)
    if args.live:
        utts.extend(LIVE)

    fast_rows = []
    agent_rows = []
    for u in utts:
        row = _bench_fast(u)
        fast_rows.append(row)
        flag = "OK" if row.get("ok") and not row.get("used_agent_loop") else "FAIL"
        print(
            f"[fast] {flag} {u!r:30s} {row.get('ms')}ms "
            f"cat={row.get('category')} band={row.get('band')} "
            f"agent_loop={row.get('used_agent_loop')}"
        )
        if args.compare_agent and row.get("category") == "A":
            arow = _bench_agent_loop_forced(u)
            agent_rows.append(arow)
            print(f"[loop]      {u!r:30s} {arow.get('ms')}ms used_agent_loop=True")

    # Brain-level integration check (must not mark AgentLoop)
    import brain
    brain_rows = []
    for u in SAFE[:3]:
        t0 = time.perf_counter()
        say, acted = brain.handle_command(u)
        ms = (time.perf_counter() - t0) * 1000.0
        brain_rows.append({
            "utt": u,
            "ms": round(ms, 2),
            "acted": acted,
            "say": (say or "")[:80],
        })
        print(f"[brain] {u!r:30s} {ms:.0f}ms acted={acted}")

    # Assertions: every SAFE Category A fast path must not use AgentLoop
    failures = []
    for r in fast_rows:
        if r["utt"] in SAFE:
            if r.get("category") != "A":
                failures.append(f"{r['utt']}: expected category A, got {r.get('category')}")
            if r.get("used_agent_loop"):
                failures.append(f"{r['utt']}: used AgentLoop on fast path")
            if not r.get("ok"):
                failures.append(f"{r['utt']}: fast path not ok")

    report = {
        "fast": {"samples": fast_rows, "stats": _stats(fast_rows)},
        "agent_loop": {"samples": agent_rows, "stats": _stats(agent_rows)} if agent_rows else None,
        "brain_handle": {"samples": brain_rows, "stats": _stats(brain_rows)},
        "assertions_failed": failures,
        "pass": len(failures) == 0,
        "architecture": {
            "old": "Speech → CapabilityRouter → AgentLoop(observe/act/verify) → Desktop",
            "new": "Speech → FastIntentRouter → Desktop (AgentLoop only on Category B or fallback)",
        },
    }
    out = Path(__file__).resolve().parent / "fast_router_bench_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + json.dumps({
        "pass": report["pass"],
        "fast_stats": report["fast"]["stats"],
        "agent_stats": (report["agent_loop"] or {}).get("stats"),
        "brain_stats": report["brain_handle"]["stats"],
        "failures": failures,
    }, indent=2))
    print(f"Wrote {out}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
