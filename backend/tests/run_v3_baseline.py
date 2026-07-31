"""NEURON V3.1 baseline harness — re-run safe tests + plan/mock reliability.

Does NOT run live desktop automation.
Records results under tests/v3_baseline_*.json for pre-V3 vs post-V3 comparison.

Usage (from backend/):
  python tests/run_v3_baseline.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent

RUNNERS = [
    "run_nlu_tests.py",
    "run_rules_tests.py",
    "run_agent_tests.py",
    "run_capability_router_tests.py",
    "run_tool_registry_tests.py",
    "run_grounded_planner_tests.py",
    "run_adaptive_loop_tests.py",
    "run_v38_multi_monitor_skills_tests.py",
    "run_v39_hardening_tests.py",
    "run_context_engine_tests.py",
    "run_reference_resolver_tests.py",
    "run_perception_engine_tests.py",
    "run_brain_phase1.py",
    "run_interrupt_tests.py",
    "run_safety_phase8.py",
    "run_memory_scopes_tests.py",
    "run_skills_tests.py",
    "run_learning_phase9.py",
    "run_computer_state_tests.py",
    "run_world_model_tests.py",
    "run_element_resolver_tests.py",
    "run_voice_phase6.py",
    "run_tts_phase7.py",
    "run_context_phase8.py",
    "run_opavr_phase9.py",
    "run_windows_phase2.py",
    "run_uia_phase3.py",
    "run_browser_phase4.py",
    "run_vision_phase5.py",
    "run_monitors_phase10.py",
]

# Pre-existing failures recorded at V3.1 audit (2026-07-30). Cleared when fixed.
KNOWN_FAILING = {
}


def _run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out


def main() -> int:
    results = []
    print("=== NEURON V3.1 baseline (safe tests) ===", flush=True)
    for name in RUNNERS:
        t0 = time.time()
        code, out = _run([sys.executable, str(ROOT / name)])
        ms = int((time.time() - t0) * 1000)
        known = KNOWN_FAILING.get(name)
        status = "PASS" if code == 0 else ("KNOWN_FAIL" if known and code != 0 else "FAIL")
        print(f"  {status:10} {name:36} exit={code} {ms}ms", flush=True)
        if code != 0 and known:
            print(f"             known: {known}", flush=True)
        results.append({
            "runner": name,
            "exit": code,
            "ms": ms,
            "status": status,
            "known_reason": known,
            "tail": "\n".join(out.strip().splitlines()[-8:]),
        })

    print("\n=== Reliability plan mode ===", flush=True)
    code_p, _ = _run([
        sys.executable, str(ROOT / "run_reliability_bench.py"),
        "--mode", "plan", "--repeats", "1",
        "--out", str(ROOT / "v3_baseline_plan.json"),
    ], timeout=120)
    print(f"  plan exit={code_p}", flush=True)

    print("\n=== Reliability mock --tag core ===", flush=True)
    code_m, _ = _run([
        sys.executable, str(ROOT / "run_reliability_bench.py"),
        "--mode", "mock", "--tag", "core", "--repeats", "1",
        "--out", str(ROOT / "v3_baseline_mock.json"),
    ], timeout=180)
    print(f"  mock exit={code_m}", flush=True)

    summary = {
        "phase": "V3.1",
        "runners": results,
        "pass": sum(1 for r in results if r["exit"] == 0),
        "fail": sum(1 for r in results if r["exit"] != 0),
        "known_fail": sum(1 for r in results if r["status"] == "KNOWN_FAIL"),
        "new_fail": sum(1 for r in results if r["status"] == "FAIL"),
        "plan_exit": code_p,
        "mock_exit": code_m,
        "known_failing": KNOWN_FAILING,
    }
    out_path = ROOT / "v3_baseline_test_results.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}", flush=True)
    print(
        f"PASS={summary['pass']} KNOWN_FAIL={summary['known_fail']} "
        f"NEW_FAIL={summary['new_fail']} TOTAL={len(results)}",
        flush=True,
    )
    # Baseline succeeds if only known failures remain
    return 0 if summary["new_fail"] == 0 and code_p == 0 and code_m == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
