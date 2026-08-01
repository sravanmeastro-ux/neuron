"""Process / host metrics (psutil optional; Windows-friendly fallbacks)."""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Sample:
    ts: float
    cpu_percent: float
    rss_mb: float
    thread_count: int
    heartbeat_age_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "cpu_percent": round(self.cpu_percent, 2),
            "rss_mb": round(self.rss_mb, 2),
            "thread_count": self.thread_count,
            "heartbeat_age_s": round(self.heartbeat_age_s, 3),
        }


_HISTORY: deque[Sample] = deque(maxlen=120)
_HEARTBEAT_TS = time.time()
_HEARTBEAT_LOCK = threading.Lock()
_PSUTIL = None


def _psutil():
    global _PSUTIL
    if _PSUTIL is False:
        return None
    if _PSUTIL is not None:
        return _PSUTIL
    try:
        import psutil  # type: ignore
        _PSUTIL = psutil
        return psutil
    except Exception:
        _PSUTIL = False
        return None


def beat_heartbeat() -> None:
    global _HEARTBEAT_TS
    with _HEARTBEAT_LOCK:
        _HEARTBEAT_TS = time.time()


def heartbeat_age() -> float:
    with _HEARTBEAT_LOCK:
        return max(0.0, time.time() - _HEARTBEAT_TS)


def _rss_mb_fallback() -> float:
    """Best-effort RSS without psutil (Windows ctypes or /proc)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            GetCurrentProcess = ctypes.windll.kernel32.GetCurrentProcess
            GetProcessMemoryInfo = ctypes.windll.psapi.GetProcessMemoryInfo
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if GetProcessMemoryInfo(GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return float(counters.WorkingSetSize) / (1024 * 1024)
        except Exception:
            pass
    try:
        # Unix
        import resource
        # ru_maxrss is KB on Linux, bytes on macOS — approximate
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return float(rss) / (1024 * 1024)
        return float(rss) / 1024.0
    except Exception:
        return 0.0


_last_cpu_times: tuple[float, float] | None = None


def _cpu_percent_fallback() -> float:
    """Approximate process CPU via time.thread_time / wall (rough)."""
    global _last_cpu_times
    try:
        cpu = time.process_time()
        wall = time.time()
        if _last_cpu_times is None:
            _last_cpu_times = (cpu, wall)
            time.sleep(0.05)
            cpu2 = time.process_time()
            wall2 = time.time()
            _last_cpu_times = (cpu2, wall2)
            dt = max(wall2 - wall, 1e-6)
            return max(0.0, min(100.0, 100.0 * (cpu2 - cpu) / dt))
        cpu0, wall0 = _last_cpu_times
        dt = max(wall - wall0, 1e-6)
        pct = 100.0 * (cpu - cpu0) / dt
        _last_cpu_times = (cpu, wall)
        return max(0.0, min(100.0 * (os.cpu_count() or 1), pct))
    except Exception:
        return 0.0


def sample_now(*, pid: int | None = None, beat: bool = True) -> Sample:
    if beat:
        beat_heartbeat()
    ps = _psutil()
    target_pid = pid or os.getpid()
    if ps is not None:
        try:
            proc = ps.Process(target_pid)
            # first cpu_percent call may be 0.0 — nudge
            cpu = float(proc.cpu_percent(interval=0.05))
            mem = float(proc.memory_info().rss) / (1024 * 1024)
            threads = int(proc.num_threads())
            s = Sample(time.time(), cpu, mem, threads, heartbeat_age())
            _HISTORY.append(s)
            return s
        except Exception:
            pass
    s = Sample(
        time.time(),
        _cpu_percent_fallback(),
        _rss_mb_fallback(),
        threading.active_count(),
        heartbeat_age(),
    )
    _HISTORY.append(s)
    return s


def history(n: int = 30) -> list[Sample]:
    items = list(_HISTORY)
    return items[-n:] if n else items


def history_dicts(n: int = 30) -> list[dict[str, Any]]:
    return [s.to_dict() for s in history(n)]


def clear_history() -> None:
    _HISTORY.clear()
