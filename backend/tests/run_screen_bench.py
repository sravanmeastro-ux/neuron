"""Screen Understanding Engine benchmarks.

Usage (from backend/):
  python tests/run_screen_bench.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.screen.planner import is_visual_command, plan_from_text
    from neuron.screen.detect import build_snapshot
    from neuron.screen.ground import ground
    from neuron.screen import handle, observe
    from neuron.screen import context as screen_ctx

    # Classifier accuracy (no side effects)
    visual_yes = [
        "Click the blue button.",
        "Click Login.",
        "Close this popup.",
        "Open the second tab.",
        "Reply to this message.",
        "Scroll until you find Blender.",
        "Read this error.",
        "What application is open?",
        "Find the download button.",
    ]
    visual_no = [
        "Open Chrome",
        "volume up",
        "mute",
        "summarize this document",
    ]
    cls_ok = 0
    cls_n = 0
    for u in visual_yes:
        cls_n += 1
        if is_visual_command(u):
            cls_ok += 1
        else:
            print(f"MISS visual: {u!r}")
    for u in visual_no:
        cls_n += 1
        if not is_visual_command(u):
            cls_ok += 1
        else:
            print(f"FALSE visual: {u!r}")

    plan_ok = 0
    for u, expect in [
        ("Click Login.", "click"),
        ("Close this popup.", "click"),
        ("Open the second tab.", "open_tab"),
        ("What application is open?", "describe"),
        ("Scroll until you find Blender.", "scroll"),
        ("Read this error.", "read"),
        ("Find the download button.", "click"),
    ]:
        p = plan_from_text(u)
        hit = p.action == expect
        plan_ok += int(hit)
        print(f"{'OK' if hit else 'FAIL'} plan {u!r} -> {p.action} (expect {expect})")

    # Live observe timings
    t0 = time.perf_counter()
    snap = build_snapshot(use_ocr=True, use_uia=True)
    observe_ms = (time.perf_counter() - t0) * 1000
    screen_ctx.remember_snapshot(snap)

    # Grounding smoke: if any button, ground its name
    ground_ok = True
    ground_score = 0.0
    if snap.buttons():
        target = snap.buttons()[0].name
        g = ground(target, snap)
        ground_ok = g.element is not None and g.score > 0
        ground_score = g.score
        print(f"{'OK' if ground_ok else 'FAIL'} ground {target!r} score={g.score:.1f}")
    else:
        print("SKIP ground (no buttons detected)")

    # Describe app (safe action)
    t1 = time.perf_counter()
    result = handle("What application is open?")
    action_ms = (time.perf_counter() - t1) * 1000
    describe_ok = bool(result and result.ok and result.acted)
    print(f"{'OK' if describe_ok else 'FAIL'} describe -> {(result.say if result else '')[:120]!r}")

    # Ensure non-visual still ignored
    none_res = handle("Open Chrome")
    skip_ok = none_res is None
    print(f"{'OK' if skip_ok else 'FAIL'} skip non-visual Open Chrome")

    # Fast router untouched smoke
    from neuron.brain.fast_router import try_handle
    fr = try_handle("mute")
    fast_ok = bool(fr and fr.ok and not fr.used_agent_loop)

    timings = dict(snap.timings_ms)
    report = {
        "classifier_accuracy": round(cls_ok / max(1, cls_n), 3),
        "planner_accuracy": round(plan_ok / 7, 3),
        "observe_ms": round(observe_ms, 2),
        "screenshot_ms": timings.get("screenshot_ms"),
        "ocr_ms": timings.get("ocr_ms"),
        "uia_ms": timings.get("uia_ms"),
        "action_ms_describe": round(action_ms, 2),
        "elements_detected": len(snap.elements),
        "ocr_lines": len(snap.ocr_text),
        "ground_ok": ground_ok,
        "ground_score": round(ground_score, 2),
        "describe_ok": describe_ok,
        "skip_non_visual_ok": skip_ok,
        "fast_router_untouched_ok": fast_ok,
        "memory": screen_ctx.summary(),
        "pass": (
            cls_ok / max(1, cls_n) >= 0.9
            and plan_ok >= 6
            and describe_ok
            and skip_ok
            and fast_ok
        ),
        "note": "False click rate requires interactive UI; not measured in this smoke.",
    }
    out = Path(__file__).resolve().parent / "screen_bench_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote {out}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
