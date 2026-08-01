"""Hot-path phase timing + production log gate for NEURON latency work."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
_LOCK = threading.Lock()
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
_CFG_CACHE: dict[str, Any] | None = None
_CFG_AT = 0.0
_JSONL_PATH = Path(__file__).resolve().parent.parent / "tests" / "perf_latency.jsonl"


def _load_cfg() -> dict[str, Any]:
    global _CFG_CACHE, _CFG_AT
    now = time.time()
    if _CFG_CACHE is not None and (now - _CFG_AT) < 2.0:
        return _CFG_CACHE
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    _CFG_CACHE = raw if isinstance(raw, dict) else {}
    _CFG_AT = now
    return _CFG_CACHE


def log_level() -> int:
    cfg = _load_cfg().get("logging") or {}
    name = str(cfg.get("level") or "INFO").upper()
    return _LEVELS.get(name, 20)


def should_log(level: str = "INFO") -> bool:
    return _LEVELS.get(str(level).upper(), 20) >= log_level()


def log(prefix: str, msg: str, *, level: str = "INFO") -> None:
    if not should_log(level):
        return
    print(f"[{prefix}] {msg}", flush=True)


class PhaseTimer:
    """Accumulate named phase durations (ms) for one command / utterance."""

    def __init__(self, label: str = ""):
        self.label = label or ""
        self.t0 = time.perf_counter()
        self.phases: dict[str, float] = {}
        self.meta: dict[str, Any] = {}

    def mark(self, name: str, ms: float | None = None) -> None:
        if ms is None:
            ms = (time.perf_counter() - self.t0) * 1000.0
        self.phases[name] = round(float(ms), 2)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = round((time.perf_counter() - start) * 1000.0, 2)

    def total_ms(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000.0, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "total_ms": self.total_ms(),
            "phases": dict(self.phases),
            "meta": dict(self.meta),
        }

    def record(self, *, append_jsonl: bool = True) -> dict[str, Any]:
        payload = self.to_dict()
        if append_jsonl:
            try:
                with _LOCK:
                    _JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
                    with _JSONL_PATH.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass
        if should_log("DEBUG"):
            print(f"[perf] {payload}", flush=True)
        return payload


# Thread-local timer for the active command (brain / agent / pipeline)
_tls = threading.local()


def current() -> PhaseTimer | None:
    return getattr(_tls, "timer", None)


def start_timer(label: str = "") -> PhaseTimer:
    timer = PhaseTimer(label=label)
    _tls.timer = timer
    return timer


def clear_timer() -> None:
    _tls.timer = None


@contextmanager
def timed_command(label: str = "") -> Iterator[PhaseTimer]:
    timer = start_timer(label)
    try:
        yield timer
    finally:
        clear_timer()
