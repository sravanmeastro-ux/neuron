"""Hot-reload watcher — poll plugin.json mtimes and reload on change."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from neuron.plugins import loader, manager

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_STATE: dict[str, Any] = {
    "running": False,
    "ticks": 0,
    "reloads": 0,
    "last_reload": None,
    "interval_s": 1.5,
    "mtimes": {},
}


def _snapshot_mtimes() -> dict[str, float]:
    out: dict[str, float] = {}
    for root in loader.discover():
        pj = root / "plugin.json"
        actions = root / "actions.py"
        try:
            out[str(pj)] = pj.stat().st_mtime
            if actions.is_file():
                out[str(actions)] = actions.stat().st_mtime
        except OSError:
            continue
    return out


def _loop(interval_s: float) -> None:
    prev = _snapshot_mtimes()
    with _LOCK:
        _STATE["mtimes"] = prev
    while not _STOP.is_set():
        try:
            cur = _snapshot_mtimes()
            changed_plugins: set[str] = set()
            for path, mtime in cur.items():
                if prev.get(path) != mtime:
                    # map path → plugin id via parent plugin.json
                    p = Path(path)
                    root = p.parent
                    try:
                        import json
                        pid = str(json.loads((root / "plugin.json").read_text(encoding="utf-8")).get("id") or root.name)
                        changed_plugins.add(pid)
                    except Exception:
                        changed_plugins.add(root.name)
            for pid in changed_plugins:
                result = manager.reload(pid)
                with _LOCK:
                    _STATE["reloads"] += 1
                    _STATE["last_reload"] = {"id": pid, "result": result, "ts": time.time()}
            prev = cur
            with _LOCK:
                _STATE["ticks"] += 1
                _STATE["mtimes"] = cur
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = str(exc)
        _STOP.wait(interval_s)
    with _LOCK:
        _STATE["running"] = False


def start_watch(*, interval_s: float = 1.5) -> dict[str, Any]:
    global _THREAD
    with _LOCK:
        if _STATE.get("running") and _THREAD and _THREAD.is_alive():
            return {"ok": True, "say": "Hot-reload watcher already running.", "state": status()}
        _STOP.clear()
        _STATE.update({"running": True, "interval_s": interval_s, "ticks": 0})
        _THREAD = threading.Thread(target=_loop, args=(interval_s,), name="neuron-plugin-hot-reload", daemon=True)
        _THREAD.start()
    return {"ok": True, "say": f"Hot-reload watcher started ({interval_s}s).", "state": status()}


def stop_watch() -> dict[str, Any]:
    global _THREAD
    _STOP.set()
    t = _THREAD
    if t and t.is_alive():
        t.join(timeout=5.0)
    with _LOCK:
        _STATE["running"] = False
    _THREAD = None
    return {"ok": True, "say": "Hot-reload watcher stopped.", "state": status()}


def status() -> dict[str, Any]:
    with _LOCK:
        st = dict(_STATE)
    st["thread_alive"] = bool(_THREAD and _THREAD.is_alive())
    return st


def reload_all() -> dict[str, Any]:
    results = []
    for p in loader.list_plugins():
        results.append(manager.reload(str(p.get("id"))))
    return {"ok": True, "results": results, "count": len(results)}
