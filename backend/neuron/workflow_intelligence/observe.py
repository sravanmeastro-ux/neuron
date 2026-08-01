"""Observation log for Cursor / GitHub / Blender / Unreal / VS Code / Browser."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from neuron.workflow_intelligence.apps import normalize_target


def _dir() -> Path:
    d = Path(__file__).resolve().parents[2] / "data" / "workflow_intelligence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def observations_path() -> Path:
    return _dir() / "observations.jsonl"


def observe(app: str, *, action: str = "focus", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    target = normalize_target(app) or (app or "").strip().lower()
    if not target:
        return {"ok": False, "error": "Need an app name"}
    event = {
        "ts": time.time(),
        "app": target,
        "action": action,
        "meta": meta or {},
    }
    path = observations_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return {"ok": True, "event": event, "path": str(path)}


def recent_observations(*, limit: int = 80, since_s: float | None = None) -> list[dict[str, Any]]:
    path = observations_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    cutoff = time.time() - since_s if since_s else 0.0
    for line in lines[-max(limit * 2, 100):]:
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if cutoff and float(ev.get("ts") or 0) < cutoff:
            continue
        rows.append(ev)
    return rows[-limit:]


def recent_app_sequence(*, window_s: float = 1800.0, limit: int = 40) -> list[str]:
    """Deduped ordered app sequence in a time window."""
    apps: list[str] = []
    for ev in recent_observations(limit=limit * 2, since_s=window_s):
        app = str(ev.get("app") or "")
        if not app:
            continue
        if apps and apps[-1] == app:
            continue
        apps.append(app)
    return apps[-limit:]


def observe_targets(targets: list[str], *, action: str = "session") -> dict[str, Any]:
    events = []
    for t in targets:
        r = observe(t, action=action)
        if r.get("ok"):
            events.append(r["event"])
    return {"ok": True, "count": len(events), "events": events}
