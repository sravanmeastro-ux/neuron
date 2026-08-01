"""Fault detectors: crash, freeze, leak, deadlock, high CPU/RAM."""

from __future__ import annotations

from typing import Any

from neuron.self_healing.metrics import Sample, history, sample_now
from neuron.self_healing.types import Fault, FaultKind


def default_thresholds() -> dict[str, float]:
    return {
        "cpu_percent": 85.0,
        "ram_mb": 1500.0,
        "freeze_heartbeat_s": 8.0,
        "leak_growth_mb": 80.0,
        "leak_samples": 8,
        "deadlock_cpu_max": 3.0,
        "deadlock_heartbeat_s": 6.0,
    }


def detect_faults(
    *,
    thresholds: dict[str, float] | None = None,
    sample: Sample | None = None,
    crashed_modules: list[dict[str, Any]] | None = None,
) -> list[Fault]:
    th = {**default_thresholds(), **(thresholds or {})}
    s = sample or sample_now()
    faults: list[Fault] = []

    # Crashes reported by registry / watchdog
    for cm in crashed_modules or []:
        faults.append(
            Fault(
                kind=FaultKind.CRASH.value,
                severity="critical",
                message=f"Module '{cm.get('name')}' crashed: {cm.get('error') or 'exit'}",
                module=str(cm.get("name") or ""),
                metrics=dict(cm),
            )
        )

    if s.cpu_percent >= th["cpu_percent"]:
        faults.append(
            Fault(
                kind=FaultKind.HIGH_CPU.value,
                severity="high",
                message=f"High CPU {s.cpu_percent:.1f}% (threshold {th['cpu_percent']}%)",
                metrics=s.to_dict(),
            )
        )

    if s.rss_mb >= th["ram_mb"]:
        faults.append(
            Fault(
                kind=FaultKind.HIGH_RAM.value,
                severity="high",
                message=f"High RAM {s.rss_mb:.1f} MB (threshold {th['ram_mb']} MB)",
                metrics=s.to_dict(),
            )
        )

    # Freeze: stale heartbeat (when watchdog beats separately from main)
    # Use history: if last samples show heartbeat_age growing while watchdog runs
    if s.heartbeat_age_s >= th["freeze_heartbeat_s"]:
        faults.append(
            Fault(
                kind=FaultKind.FREEZE.value,
                severity="critical",
                message=f"Possible freeze: heartbeat age {s.heartbeat_age_s:.1f}s",
                metrics=s.to_dict(),
            )
        )

    # Deadlock heuristic: freeze-like stall + near-idle CPU
    if s.heartbeat_age_s >= th["deadlock_heartbeat_s"] and s.cpu_percent <= th["deadlock_cpu_max"]:
        faults.append(
            Fault(
                kind=FaultKind.DEADLOCK.value,
                severity="critical",
                message=(
                    f"Possible deadlock: heartbeat age {s.heartbeat_age_s:.1f}s "
                    f"with CPU {s.cpu_percent:.1f}%"
                ),
                metrics=s.to_dict(),
            )
        )

    leak = _detect_leak(th)
    if leak:
        faults.append(leak)

    return faults


def _detect_leak(th: dict[str, float]) -> Fault | None:
    hist = history(int(th.get("leak_samples", 8)) + 2)
    need = int(th.get("leak_samples", 8))
    if len(hist) < need:
        return None
    window = hist[-need:]
    growth = window[-1].rss_mb - window[0].rss_mb
    # monotonic-ish growth
    ups = sum(1 for i in range(1, len(window)) if window[i].rss_mb >= window[i - 1].rss_mb - 0.5)
    if growth >= th["leak_growth_mb"] and ups >= need - 2:
        return Fault(
            kind=FaultKind.MEMORY_LEAK.value,
            severity="high",
            message=f"Possible memory leak: RSS grew {growth:.1f} MB over {need} samples",
            metrics={
                "growth_mb": round(growth, 2),
                "start_mb": round(window[0].rss_mb, 2),
                "end_mb": round(window[-1].rss_mb, 2),
                "samples": [x.to_dict() for x in window],
            },
        )
    return None


def health_snapshot(thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    s = sample_now()
    faults = detect_faults(thresholds=thresholds, sample=s)
    return {
        "ok": not faults,
        "sample": s.to_dict(),
        "faults": [f.to_dict() for f in faults],
        "fault_kinds": [f.kind for f in faults],
        "status": "degraded" if faults else "healthy",
    }
