"""NEURON reliability benchmark CLI.

Prefer 100 workflows at 95%+ reliability over thousands of flaky commands.

Examples:
  python tests/run_reliability_bench.py
  python tests/run_reliability_bench.py --mode mock --repeats 3
  python tests/run_reliability_bench.py --mode plan --tag core --repeats 5
  python tests/run_reliability_bench.py --mode live --ids open_chrome,open_notepad --repeats 2
  python tests/run_reliability_bench.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    from tests.reliability.tasks import TASKS, filter_tasks
    from tests.reliability.runner import print_summary, run_benchmark, write_report

    p = argparse.ArgumentParser(description="NEURON desktop reliability benchmark")
    p.add_argument("--mode", choices=("plan", "mock", "live"), default="plan",
                   help="plan=score fixed plans; mock=AgentLoop+stub tools; live=real desktop")
    p.add_argument("--repeats", type=int, default=3, help="attempts per task")
    p.add_argument("--category", default="", help="filter category")
    p.add_argument("--tag", default="", help="filter tag (e.g. core)")
    p.add_argument("--ids", default="", help="comma-separated task ids")
    p.add_argument("--limit", type=int, default=0, help="cap number of tasks")
    p.add_argument("--list", action="store_true", help="list tasks and exit")
    p.add_argument("--out", default="", help="write JSON report path")
    args = p.parse_args(argv)

    if args.list:
        rows = filter_tasks(category=args.category, tag=args.tag)
        print(f"{len(rows)} tasks (catalog {len(TASKS)}):")
        for t in rows:
            tags = ",".join(t.get("tags") or [])
            print(f"  {t['id']:28} [{t['category']:10}] {t['name']}  {{{tags}}}")
        return 0

    ids = [x.strip() for x in args.ids.split(",") if x.strip()] or None
    report = run_benchmark(
        mode=args.mode,
        repeats=max(1, args.repeats),
        category=args.category,
        tag=args.tag,
        ids=ids,
        limit=args.limit,
    )
    print_summary(report)
    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "reliability_report.json"
    path = write_report(report, out)
    print(f"\nWrote {path}", flush=True)
    # Exit 0 for plan/mock harness health; live uses rate target
    if args.mode in ("plan", "mock"):
        return 0 if report["task_success_rate"] >= 0.95 else 1
    return 0 if report["meets_target"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
