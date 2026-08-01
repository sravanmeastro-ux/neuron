"""Dependency graph from project manifests (read-only)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from neuron.developer.index import index_project, resolve_root


def dependency_graph(root: str | None = None) -> dict[str, Any]:
    root_p = resolve_root(root)
    idx = index_project(root_p)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    # package.json
    pkg = root_p / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            name = data.get("name") or root_p.name
            nodes[name] = {"id": name, "kind": "app", "ecosystem": "node"}
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for dep, ver in (data.get(section) or {}).items():
                    nodes[dep] = {"id": dep, "kind": "package", "ecosystem": "node", "version": ver}
                    edges.append({"from": name, "to": dep, "type": section})
        except Exception:
            pass

    # requirements.txt
    req = root_p / "requirements.txt"
    if req.is_file():
        nodes[root_p.name] = nodes.get(root_p.name) or {"id": root_p.name, "kind": "app", "ecosystem": "python"}
        for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"([A-Za-z0-9_.\-]+)", line)
            if m:
                dep = m.group(1)
                nodes[dep] = {"id": dep, "kind": "package", "ecosystem": "python"}
                edges.append({"from": root_p.name, "to": dep, "type": "requirements"})

    # pyproject.toml — light parse
    pyproject = root_p / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        nodes[root_p.name] = nodes.get(root_p.name) or {"id": root_p.name, "kind": "app", "ecosystem": "python"}
        for m in re.finditer(r'^\s*"([A-Za-z0-9_.\-]+)"\s*[>=<]', text, re.M):
            dep = m.group(1)
            nodes[dep] = {"id": dep, "kind": "package", "ecosystem": "python"}
            edges.append({"from": root_p.name, "to": dep, "type": "pyproject"})

    # Cargo.toml
    cargo = root_p / "Cargo.toml"
    if cargo.is_file():
        text = cargo.read_text(encoding="utf-8", errors="ignore")
        nodes[root_p.name] = nodes.get(root_p.name) or {"id": root_p.name, "kind": "app", "ecosystem": "rust"}
        in_deps = False
        for line in text.splitlines():
            if line.strip().startswith("[dependencies"):
                in_deps = True
                continue
            if line.strip().startswith("["):
                in_deps = False
            if in_deps:
                m = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*=", line)
                if m:
                    dep = m.group(1)
                    nodes[dep] = {"id": dep, "kind": "package", "ecosystem": "rust"}
                    edges.append({"from": root_p.name, "to": dep, "type": "cargo"})

    return {
        "root": str(root_p),
        "languages": idx.languages,
        "frameworks": idx.frameworks,
        "nodes": list(nodes.values())[:200],
        "edges": edges[:400],
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
