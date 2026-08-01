"""Background watchdog service — poll metrics, detect faults, auto-recover."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from neuron.self_healing.detectors import default_thresholds, detect_faults, health_snapshot
from neuron.self_healing.metrics import beat_heartbeat, sample_now
from neuron.self_healing.recovery import ensure_builtin_modules, recover_from_faults

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_STATE: dict[str, Any] = {
    "running": False,
    "started_at": 0.0,
    "ticks": 0,
    "last_sample": None,
    "last_faults": [],
    "last_recovery": None,
    "recoveries": 0,
    "interval_s": 2.0,
    "auto_recover": True,
}


def _log_dir() -> Path:
    d = Path(__file__).resolve().parents[2] / "data" / "self_healing"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _append_log(event: dict[str, Any]) -> None:
    path = _log_dir() / "watchdog.jsonl"
    event = {**event, "ts": time.time()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def _load_thresholds() -> dict[str, float]:
    th = default_thresholds()
    try:
        cfg_path = Path(__file__).resolve().parents[2] / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        section = cfg.get("self_healing") or {}
        for k in th:
            if k in section:
                th[k] = float(section[k])
        # nested thresholds dict
        nested = section.get("thresholds") or {}
        for k, v in nested.items():
            th[k] = float(v)
    except Exception:
        pass
    return th


def _loop(interval_s: float, auto_recover: bool) -> None:
    ensure_builtin_modules()
    th = _load_thresholds()
    # Separate "main" heartbeat: watchdog does NOT call beat_heartbeat on every tick
    # so freeze can be detected if host stops calling beat. We expose tick_heartbeat
    # for agent.run to call; watchdog only samples.
    while not _STOP.is_set():
        try:
            sample = sample_now(beat=False)
            faults = detect_faults(thresholds=th, sample=sample)
            with _LOCK:
                _STATE["ticks"] += 1
                _STATE["last_sample"] = sample.to_dict()
                _STATE["last_faults"] = [f.to_dict() for f in faults]
            if faults:
                _append_log({"event": "faults", "faults": [f.to_dict() for f in faults], "sample": sample.to_dict()})
                if auto_recover:
                    rec = recover_from_faults(faults, auto=True)
                    with _LOCK:
                        _STATE["last_recovery"] = rec
                        _STATE["recoveries"] += 1
                    _append_log({"event": "recovery", "recovery": rec})
        except Exception as exc:
            _append_log({"event": "watchdog_error", "error": str(exc)})
        _STOP.wait(interval_s)

    with _LOCK:
        _STATE["running"] = False


def start_watchdog(*, interval_s: float = 2.0, auto_recover: bool = True) -> dict[str, Any]:
    global _THREAD
    with _LOCK:
        if _STATE.get("running") and _THREAD and _THREAD.is_alive():
            return {"ok": True, "say": "Watchdog already running.", "state": status()}
        _STOP.clear()
        _STATE.update(
            {
                "running": True,
                "started_at": time.time(),
                "ticks": 0,
                "interval_s": interval_s,
                "auto_recover": auto_recover,
                "recoveries": _STATE.get("recoveries", 0),
            }
        )
        _THREAD = threading.Thread(target=_loop, args=(interval_s, auto_recover), name="neuron-self-healing-watchdog", daemon=True)
        _THREAD.start()
    _append_log({"event": "watchdog_start", "interval_s": interval_s, "auto_recover": auto_recover})
    return {"ok": True, "say": f"Watchdog started (interval={interval_s}s, auto_recover={auto_recover}).", "state": status()}


def stop_watchdog() -> dict[str, Any]:
    global _THREAD
    _STOP.set()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=5.0)
    with _LOCK:
        _STATE["running"] = False
    _THREAD = None
    _append_log({"event": "watchdog_stop"})
    return {"ok": True, "say": "Watchdog stopped.", "state": status()}


def status() -> dict[str, Any]:
    with _LOCK:
        st = dict(_STATE)
    st["thread_alive"] = bool(_THREAD and _THREAD.is_alive())
    st["log_dir"] = str(_log_dir())
    return st


def tick_main_heartbeat() -> None:
    """Call from agent.run / main loop so freeze detection is meaningful."""
    beat_heartbeat()


def run_once(*, auto_recover: bool = True) -> dict[str, Any]:
    """Single scan + optional recover (for voice / tools)."""
    ensure_builtin_modules()
    snap = health_snapshot(_load_thresholds())
    recovery = None
    if snap.get("faults") and auto_recover:
        recovery = recover_from_faults(snap["faults"], auto=True)
        with _LOCK:
            _STATE["last_recovery"] = recovery
            _STATE["recoveries"] = int(_STATE.get("recoveries") or 0) + 1
        _append_log({"event": "run_once_recovery", "recovery": recovery, "faults": snap["faults"]})
    with _LOCK:
        _STATE["last_sample"] = snap.get("sample")
        _STATE["last_faults"] = snap.get("faults") or []
    return {"health": snap, "recovery": recovery}
