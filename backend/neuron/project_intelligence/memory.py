"""Persistent architecture / module / relationship memory."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from neuron.developer.index import resolve_root
from neuron.project_intelligence.graph import build_project_graph
from neuron.project_intelligence.indexer import deep_index


def _store_dir() -> Path:
    d = Path(__file__).resolve().parents[2] / "data" / "project_intelligence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_path(root: str | Path | None = None) -> Path:
    root_p = resolve_root(str(root) if root else None)
    safe = re_safe(root_p.name)
    return _store_dir() / f"memory_{safe}.json"


def re_safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:64]


def remember_project(root: str | Path | None = None, *, rebuild_graph: bool = True) -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    idx = deep_index(root_p)
    graph = build_project_graph(root_p) if rebuild_graph else {}
    relationships = [
        {"from": e.get("from"), "to": e.get("to"), "rel": e.get("rel")}
        for e in (graph.get("edges") or [])
        if e.get("rel") in ("contains", "imports")
    ][:200]

    architecture = {
        "summary": (idx.get("readme") or {}).get("summary") or "",
        "title": (idx.get("readme") or {}).get("title") or idx.get("name"),
        "languages": idx.get("languages") or {},
        "entry_areas": [m.get("module") for m in (idx.get("modules") or [])[:15]],
        "docs": [d.get("path") for d in (idx.get("docs") or [])[:20]],
        "build_dirs": idx.get("build_dirs") or [],
        "dependency_ecosystems": list((idx.get("dependencies") or {}).keys()),
    }

    payload = {
        "root": str(root_p),
        "updated_at": time.time(),
        "architecture": architecture,
        "modules": idx.get("modules") or [],
        "relationships": relationships,
        "index_stats": {
            "sources": idx.get("source_count"),
            "assets": idx.get("asset_count"),
            "docs": idx.get("doc_count"),
            "folders": idx.get("folder_count"),
            "build_dirs": idx.get("build_dir_count"),
        },
        "graph_paths": (graph.get("paths") or {}),
    }
    path = memory_path(root_p)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["memory_path"] = str(path)
    return payload


def load_memory(root: str | Path | None = None) -> dict[str, Any] | None:
    path = memory_path(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_or_build_memory(root: str | Path | None = None) -> dict[str, Any]:
    mem = load_memory(root)
    if mem:
        return mem
    return remember_project(root)
