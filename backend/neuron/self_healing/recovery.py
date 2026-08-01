"""Restartable module registry + recovery actions."""

from __future__ import annotations

import gc
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from neuron.self_healing.types import Fault, FaultKind

RestartFn = Callable[[], dict[str, Any]]


@dataclass
class ModuleSpec:
    name: str
    restart: RestartFn
    description: str = ""
    last_ok: float = 0.0
    last_error: str = ""
    crash_count: int = 0
    enabled: bool = True


_MODULES: dict[str, ModuleSpec] = {}
_CRASH_LOG: list[dict[str, Any]] = []


def register_module(name: str, restart: RestartFn, *, description: str = "") -> None:
    _MODULES[name] = ModuleSpec(name=name, restart=restart, description=description)


def list_modules() -> list[dict[str, Any]]:
    return [
        {
            "name": m.name,
            "description": m.description,
            "last_ok": m.last_ok,
            "last_error": m.last_error,
            "crash_count": m.crash_count,
            "enabled": m.enabled,
        }
        for m in _MODULES.values()
    ]


def crashed_modules() -> list[dict[str, Any]]:
    return list(_CRASH_LOG[-20:])


def report_crash(name: str, error: str) -> None:
    if name in _MODULES:
        _MODULES[name].crash_count += 1
        _MODULES[name].last_error = error
    _CRASH_LOG.append({"name": name, "error": error, "ts": time.time()})


def restart_module(name: str) -> dict[str, Any]:
    m = _MODULES.get(name)
    if not m:
        return {"ok": False, "error": f"Unknown module: {name}"}
    if not m.enabled:
        return {"ok": False, "error": f"Module disabled: {name}"}
    try:
        result = m.restart() or {}
        m.last_ok = time.time()
        m.last_error = ""
        return {"ok": True, "name": name, "result": result}
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()[-400:]}"
        report_crash(name, str(exc))
        return {"ok": False, "name": name, "error": err}


def restart_failed_modules() -> dict[str, Any]:
    """Restart modules that previously crashed or have last_error."""
    targets = [m.name for m in _MODULES.values() if m.crash_count or m.last_error]
    if not targets:
        # Still bounce soft caches as a recovery pass
        targets = list(_MODULES.keys())
    results = []
    for name in targets:
        results.append(restart_module(name))
    ok = all(r.get("ok") for r in results) if results else True
    return {"ok": ok, "results": results, "count": len(results)}


def ensure_builtin_modules() -> None:
    """Register soft-restart hooks for NEURON subsystems (compose-only)."""
    if _MODULES:
        return

    def _clear_pi():
        try:
            from neuron.project_intelligence.indexer import clear_index_cache
            clear_index_cache()
        except Exception:
            pass
        return {"cleared": "project_intelligence_cache"}

    def _clear_dev():
        try:
            from neuron.developer.index import clear_index_cache
            clear_index_cache()
        except Exception:
            pass
        return {"cleared": "developer_index_cache"}

    def _rebootstrap_tools():
        try:
            from neuron.brain import tool_registry
            # Soft: ensure_bootstrapped is one-shot; clear flag if present
            if hasattr(tool_registry, "_BOOTSTRAPPED"):
                tool_registry._BOOTSTRAPPED = False  # type: ignore[attr-defined]
            tool_registry.ensure_bootstrapped()
            return {"tools": "re-bootstrapped"}
        except Exception as exc:
            return {"error": str(exc)}

    def _gc():
        n = gc.collect()
        return {"collected": n}

    def _metrics_hist():
        from neuron.self_healing.metrics import clear_history
        clear_history()
        return {"history": "cleared"}

    register_module("gc", _gc, description="Force garbage collection")
    register_module("project_intelligence", _clear_pi, description="Clear PI index cache")
    register_module("developer_index", _clear_dev, description="Clear developer project index cache")
    register_module("tool_registry", _rebootstrap_tools, description="Re-bootstrap tool registry")
    register_module("metrics_history", _metrics_hist, description="Clear metrics history")


def recover_from_faults(faults: list[Fault] | list[dict[str, Any]], *, auto: bool = True) -> dict[str, Any]:
    ensure_builtin_modules()
    actions: list[str] = []
    details: list[dict[str, Any]] = []

    norm: list[dict[str, Any]] = []
    for f in faults:
        if isinstance(f, Fault):
            norm.append(f.to_dict())
        else:
            norm.append(f)

    kinds = {f.get("kind") for f in norm}

    if FaultKind.HIGH_RAM.value in kinds or FaultKind.MEMORY_LEAK.value in kinds:
        details.append(restart_module("gc"))
        actions.append("gc.collect")
        details.append(restart_module("project_intelligence"))
        actions.append("clear_project_intelligence_cache")
        details.append(restart_module("developer_index"))
        actions.append("clear_developer_index")
        details.append(restart_module("metrics_history"))
        actions.append("clear_metrics_history")

    if FaultKind.HIGH_CPU.value in kinds:
        # Yield briefly to cool down
        time.sleep(0.15)
        actions.append("yield_cpu")

    if FaultKind.CRASH.value in kinds or FaultKind.FREEZE.value in kinds or FaultKind.DEADLOCK.value in kinds:
        r = restart_failed_modules()
        details.append(r)
        actions.append("restart_failed_modules")
        details.append(restart_module("tool_registry"))
        actions.append("rebootstrap_tools")

    if not kinds and auto:
        details.append(restart_module("gc"))
        actions.append("gc.collect_proactive")

    return {
        "ok": True,
        "actions": actions,
        "details": details,
        "fault_kinds": sorted(k for k in kinds if k),
    }
