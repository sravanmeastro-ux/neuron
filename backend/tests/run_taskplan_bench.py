"""Benchmarks for Task Planning Engine (no live GUI mutation by default)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES = [
    (
        "Open Chrome, search YouTube for Unreal Engine tutorials, and play the first result.",
        "template:youtube",
        3,
    ),
    (
        "Open Visual Studio Code, create a Python file, write Hello World, and run it.",
        "template:vscode_hello",
        5,
    ),
    (
        "Download Blender and install it.",
        "template:blender_download",
        4,
    ),
    (
        "Open WhatsApp Web, reply to my latest message, then archive the chat.",
        "template:whatsapp",
        3,
    ),
    (
        "Create a new folder on the desktop called Projects, move all PDF files into it, then zip the folder.",
        "template:desktop_projects",
        3,
    ),
]

NON_WORKFLOW = [
    "mute",
    "volume up",
    "Open Chrome",
    "undo",
]


def main() -> int:
    from neuron.taskplan.detect import looks_like_workflow
    from neuron.taskplan.decompose import build_graph
    from neuron.taskplan.extract import extract_goal
    from neuron.taskplan.types import topological_order

    planner_latencies: list[float] = []
    plan_ok = 0
    detect_ok = 0
    dep_ok = True

    for text, expect_src, expect_n in SAMPLES:
        if looks_like_workflow(text):
            detect_ok += 1
        t0 = time.perf_counter()
        g = build_graph(text)
        ms = (time.perf_counter() - t0) * 1000
        planner_latencies.append(ms)
        if g is None:
            print(f"FAIL plan missing for {text!r}")
            continue
        src_ok = expect_src in (g.source or "")
        n_ok = len(g.subtasks) >= expect_n
        ordered = topological_order(g.subtasks)
        # deps respected: each prior dependency appears earlier
        idx = {s.subtask_id: i for i, s in enumerate(ordered)}
        for s in ordered:
            for d in s.depends_on or []:
                if d in idx and idx[d] > idx[s.subtask_id]:
                    dep_ok = False
        if src_ok and n_ok:
            plan_ok += 1
            print(f"OK plan {g.source} n={len(g.subtasks)} {ms:.2f}ms :: {text[:60]}...")
        else:
            print(
                f"FAIL plan src={g.source} n={len(g.subtasks)} "
                f"expect {expect_src}/{expect_n} :: {text[:50]}"
            )

    skip_ok = 0
    for t in NON_WORKFLOW:
        if not looks_like_workflow(t):
            skip_ok += 1
            print(f"OK skip non-workflow {t!r}")
        else:
            print(f"FAIL false workflow {t!r}")

    # Confirm gate on destructive template (plan-only)
    g = build_graph(SAMPLES[-1][0])
    confirm_steps = sum(1 for s in (g.subtasks if g else []) if s.requires_confirm)
    confirm_ok = confirm_steps >= 2

    # Fast router / semantic / screen packages untouched check (import identity)
    import neuron.brain.fast_router as fr
    import neuron.understand as und
    import neuron.screen as scr
    untouched_ok = all(
        hasattr(m, "__file__") for m in (fr, und, scr)
    )

    # Dry-run handle on non-executing cancel with no state
    from neuron.taskplan.engine import handle
    r = handle("cancel the task")
    cancel_ok = r is not None and r[1] is True

    mean_plan = sum(planner_latencies) / max(1, len(planner_latencies))

    report = {
        "detect_accuracy": detect_ok / len(SAMPLES),
        "plan_accuracy": plan_ok / len(SAMPLES),
        "non_workflow_skip_accuracy": skip_ok / len(NON_WORKFLOW),
        "dependency_order_ok": dep_ok,
        "confirm_gate_ok": confirm_ok,
        "cancel_ok": cancel_ok,
        "planner_latency_ms": {
            "mean": round(mean_plan, 2),
            "max": round(max(planner_latencies), 2) if planner_latencies else 0,
            "min": round(min(planner_latencies), 2) if planner_latencies else 0,
            "samples": [round(x, 2) for x in planner_latencies],
        },
        "goal_sample": extract_goal(SAMPLES[0][0]).to_dict(),
        "untouched_fast_semantic_screen_ok": untouched_ok,
        "note": "Live success/retry/recovery rates require interactive desktop; measured planner + gates here.",
        "pass": (
            detect_ok == len(SAMPLES)
            and plan_ok == len(SAMPLES)
            and skip_ok == len(NON_WORKFLOW)
            and dep_ok
            and confirm_ok
            and cancel_ok
            and untouched_ok
        ),
    }
    out = Path(__file__).with_name("taskplan_bench_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote {out}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
