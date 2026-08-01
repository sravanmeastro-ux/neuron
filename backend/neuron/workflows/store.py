"""Workflow persistence."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from neuron.workflows.types import Workflow

_LOCK = threading.Lock()
_STORE: Path | None = None


def store_path() -> Path:
    global _STORE
    if _STORE is not None:
        return _STORE
    root = Path(__file__).resolve().parents[2]  # backend/
    try:
        cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
        custom = ((cfg.get("workflows") or {}).get("store") or "").strip()
        if custom:
            _STORE = Path(custom)
            return _STORE
    except Exception:
        pass
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    _STORE = data / "workflows.json"
    return _STORE


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s or "workflow")[:48]


def _load_raw() -> dict[str, Any]:
    path = store_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"workflows": [], "updated": ""}


def _save_raw(data: dict[str, Any]) -> None:
    data = dict(data)
    data["updated"] = _now()
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_workflows() -> list[Workflow]:
    with _LOCK:
        rows = _load_raw().get("workflows") or []
        return [Workflow.from_dict(r) for r in rows]


def get(workflow_id: str) -> Workflow | None:
    wid = (workflow_id or "").strip().lower()
    if not wid:
        return None
    for w in list_workflows():
        if w.id.lower() == wid or w.name.lower() == wid:
            return w
    # fuzzy say match
    q = re.sub(r"\s+", " ", wid)
    for w in list_workflows():
        say = re.sub(r"\s+", " ", (w.name or "").lower())
        if q in say or say in q:
            return w
    return None


def save(workflow: Workflow, *, replace: bool = True) -> Workflow:
    with _LOCK:
        data = _load_raw()
        rows: list[dict] = list(data.get("workflows") or [])
        if not workflow.id:
            workflow.id = _slug(workflow.name or "workflow") + "-" + str(int(time.time()) % 100000)
        if not workflow.created:
            workflow.created = _now()
        workflow.updated = _now()
        workflow.version = int(workflow.version or 1)
        payload = workflow.to_dict()
        if replace:
            rows = [r for r in rows if str(r.get("id") or "").lower() != workflow.id.lower()]
        rows.append(payload)
        data["workflows"] = rows[-120:]
        _save_raw(data)
        return workflow


def delete(workflow_id: str) -> bool:
    with _LOCK:
        data = _load_raw()
        rows = data.get("workflows") or []
        n = len(rows)
        rows = [r for r in rows if str(r.get("id") or "").lower() != (workflow_id or "").lower()]
        if len(rows) == n:
            return False
        data["workflows"] = rows
        _save_raw(data)
        return True


def new_id(name: str) -> str:
    return _slug(name) + "-" + str(int(time.time()) % 100000)
