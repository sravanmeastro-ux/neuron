"""Perf baseline — measure brain.handle_command phase timings (no mic).

Usage (from backend/):
  python tests/run_perf_baseline.py
  python tests/run_perf_baseline.py --live   # allows desktop side-effects

Writes: tests/perf_baseline_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Safe phrases: volume/mute don't need windows; open uses focus-if-running
SAFE = [
    ("volume up", "fast_volume"),
    ("volume down", "fast_volume"),
    ("mute", "fast_volume"),
]

LIVE = [
    ("open notepad", "open_app"),
    ("open chrome", "open_app"),
]


def _run_one(text: str) -> dict:
    from neuron.perf import timed_command
    import brain

    with timed_command(label=text) as timer:
        t0 = time.perf_counter()
        reply, acted = brain.handle_command(text)
        timer.mark("brain_ms", (time.perf_counter() - t0) * 1000.0)
        timer.meta["reply"] = (reply or "")[:120]
        timer.meta["acted"] = acted
        payload = timer.record(append_jsonl=True)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="Include open-app samples")
    args = ap.parse_args()

    samples = list(SAFE)
    if args.live:
        samples.extend(LIVE)

    rows = []
    for text, kind in samples:
        try:
            row = _run_one(text)
            row["kind"] = kind
            rows.append(row)
            print(
                f"OK  {text!r:30s} total={row['total_ms']:.0f}ms "
                f"phases={row.get('phases')} path={row.get('meta', {}).get('path')}"
            )
        except Exception as exc:
            print(f"FAIL {text!r}: {exc}")
            rows.append({"label": text, "kind": kind, "error": str(exc)})

    totals = [r["total_ms"] for r in rows if "total_ms" in r]
    report = {
        "n": len(totals),
        "mean_ms": round(sum(totals) / len(totals), 2) if totals else None,
        "min_ms": round(min(totals), 2) if totals else None,
        "max_ms": round(max(totals), 2) if totals else None,
        "samples": rows,
        "note": "brain.handle_command only (no STT/VAD). Volume path should be <<1s.",
    }
    out = Path(__file__).resolve().parent / "perf_baseline_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    print(json.dumps({k: report[k] for k in ("n", "mean_ms", "min_ms", "max_ms")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
