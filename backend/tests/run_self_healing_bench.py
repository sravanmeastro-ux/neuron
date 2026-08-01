"""Benchmarks for Self-Healing."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.self_healing import looks_like_self_healing, orchestrate, dispatch
    from neuron.self_healing.detect import classify_sh_intent
    from neuron.self_healing.types import FaultKind, SHCapability
    from neuron.self_healing import metrics, detectors, recovery, watchdog
    from neuron.self_healing.bridge import maybe_handle_self_healing
    from neuron.self_healing.types import Fault

    assert not looks_like_self_healing("mute")
    assert not looks_like_self_healing("Open Chrome")
    assert not looks_like_self_healing("Find memory leaks.")  # Project Intelligence
    assert looks_like_self_healing("Start the watchdog")
    assert looks_like_self_healing("System health")
    assert looks_like_self_healing("Restart failed modules")
    assert looks_like_self_healing("High CPU")
    print("OK detect")

    assert classify_sh_intent("Start the watchdog")["capability"] == SHCapability.WATCHDOG_START.value
    assert classify_sh_intent("System health")["capability"] == SHCapability.SCAN.value
    assert classify_sh_intent("Restart failed modules")["capability"] == SHCapability.RESTART_MODULE.value
    print("OK classify")

    metrics.clear_history()
    s = metrics.sample_now(beat=True)
    assert s.rss_mb >= 0
    print(f"OK metrics cpu={s.cpu_percent:.1f} rss={s.rss_mb:.1f}MB threads={s.thread_count}")

    # High CPU via low threshold
    faults = detectors.detect_faults(
        thresholds={"cpu_percent": -1.0, "ram_mb": 1e9},
        sample=s,
    )
    assert any(f.kind == FaultKind.HIGH_CPU.value for f in faults)
    print("OK detect_high_cpu")

    # Crash via registry
    recovery.ensure_builtin_modules()
    recovery.report_crash("gc", "simulated")
    faults2 = detectors.detect_faults(crashed_modules=recovery.crashed_modules(), sample=s)
    assert any(f.kind == FaultKind.CRASH.value for f in faults2)
    print("OK detect_crash")

    # Memory leak trend
    metrics.clear_history()
    base = time.time()
    for i in range(10):
        metrics._HISTORY.append(
            metrics.Sample(base + i, 5.0, 100.0 + i * 15.0, 10, 0.1)
        )
    leak = detectors._detect_leak(detectors.default_thresholds())
    assert leak and leak.kind == FaultKind.MEMORY_LEAK.value
    print("OK detect_leak")

    # Deadlock / freeze heuristics
    frozen = metrics.Sample(time.time(), 0.5, 200.0, 8, 10.0)
    faults3 = detectors.detect_faults(thresholds=detectors.default_thresholds(), sample=frozen)
    kinds = {f.kind for f in faults3}
    assert FaultKind.FREEZE.value in kinds
    assert FaultKind.DEADLOCK.value in kinds
    print("OK detect_freeze_deadlock")

    rec = recovery.recover_from_faults([Fault(kind=FaultKind.HIGH_RAM.value, message="test")])
    assert "gc.collect" in rec.get("actions", [])
    print(f"OK recover actions={rec.get('actions')}")

    r = recovery.restart_module("gc")
    assert r.get("ok")
    print("OK restart_module")

    fr = recovery.restart_failed_modules()
    assert fr.get("count", 0) >= 1
    print("OK restart_failed")

    wd = watchdog.start_watchdog(interval_s=0.3, auto_recover=True)
    assert wd.get("ok")
    time.sleep(0.9)
    st = watchdog.status()
    assert st.get("running") and st.get("ticks", 0) >= 1
    print(f"OK watchdog ticks={st.get('ticks')}")
    watchdog.stop_watchdog()
    assert not watchdog.status().get("running")
    print("OK watchdog_stop")

    say, acted, meta = orchestrate("System health")
    assert acted and meta.get("path") == "self_healing"
    print(f"OK orchestrate say={say[:80]!r}")

    assert maybe_handle_self_healing("mute") is None
    assert maybe_handle_self_healing("Find memory leaks.") is None
    hit = maybe_handle_self_healing("Start the watchdog")
    assert hit is not None
    watchdog.stop_watchdog()
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("self_heal_status")
    assert tool_registry.get("self_heal_run")
    print("OK tools")

    print("PASS self_healing_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
