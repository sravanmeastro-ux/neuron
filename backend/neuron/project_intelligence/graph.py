"""Module / import relationship graphs + Mermaid export."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from neuron.developer.index import resolve_root
from neuron.project_intelligence.indexer import deep_index

_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
    re.M,
)
_JS_IMPORT = re.compile(
    r"""(?:import\s+(?:[\w*{}\s,]+\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))""",
)


def build_project_graph(root: str | Path | None = None, *, max_edges: int = 400) -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    idx = deep_index(root_p)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    # Module nodes from indexer
    for m in idx.get("modules") or []:
        mid = m["module"]
        nodes[mid] = {"id": mid, "kind": "module", "files": m.get("files", 0)}

    # Folder category nodes
    for label, key in (
        ("docs", "doc_count"),
        ("assets", "asset_count"),
        ("build", "build_dir_count"),
        ("dependencies", "dependency_manifests"),
    ):
        val = idx.get(key)
        if isinstance(val, list):
            weight = len(val)
        else:
            weight = int(val or 0)
        if weight:
            nodes[label] = {"id": label, "kind": "category", "files": weight}
            edges.append({"from": idx.get("name") or root_p.name, "to": label, "rel": "contains"})

    project = idx.get("name") or root_p.name
    nodes[project] = {"id": project, "kind": "project", "files": idx.get("source_count", 0)}
    for m in (idx.get("modules") or [])[:25]:
        edges.append({"from": project, "to": m["module"], "rel": "contains"})

    # Import edges among source files (sampled)
    import_edges = _scan_imports(root_p, idx.get("sources_sample") or idx.get("sources") or [])
    # Prefer module-level edges
    mod_edges: dict[tuple[str, str], int] = defaultdict(int)
    for src, dst in import_edges:
        sm = _module_of(src)
        dm = _module_of(dst) if not dst.startswith(".") else sm
        if dm.startswith(".") or "/" not in dm and dm in ("os", "sys", "re", "json", "pathlib", "typing"):
            continue
        # relative imports stay within package — keep file-ish module key
        if sm and dm and sm != dm:
            mod_edges[(sm, dm)] += 1

    for (a, b), n in sorted(mod_edges.items(), key=lambda x: -x[1])[:max_edges]:
        if a not in nodes:
            nodes[a] = {"id": a, "kind": "module", "files": 0}
        if b not in nodes:
            nodes[b] = {"id": b, "kind": "external" if b.startswith("@") or "." not in b and "/" not in b else "module", "files": 0}
        edges.append({"from": a, "to": b, "rel": "imports", "weight": n})

    # Dep package nodes (external)
    for eco, pkgs in (idx.get("dependencies") or {}).items():
        for pkg in (pkgs or [])[:30]:
            nid = f"{eco}:{pkg}"
            nodes[nid] = {"id": nid, "kind": "dependency", "eco": eco}
            edges.append({"from": project, "to": nid, "rel": "depends_on"})

    mermaid = _to_mermaid(project, list(nodes.values()), edges)
    out_dir = Path(__file__).resolve().parents[2] / "data" / "project_intelligence"
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / "project_graph.mmd"
    json_path = out_dir / "project_graph.json"
    payload = {
        "root": str(root_p),
        "project": project,
        "nodes": list(nodes.values()),
        "edges": edges[: max_edges + 80],
        "mermaid": mermaid,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "modules": len(idx.get("modules") or []),
            "languages": idx.get("languages") or {},
        },
    }
    graph_path.write_text(mermaid, encoding="utf-8")
    json_path.write_text(__import__("json").dumps(payload, indent=2)[:500_000], encoding="utf-8")
    payload["paths"] = {"mermaid": str(graph_path), "json": str(json_path)}
    return payload


def _module_of(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if not parts:
        return rel_path
    if parts[0] in ("src", "lib", "app", "apps", "packages", "backend", "frontend", "server", "client", "neuron"):
        return "/".join(parts[:2]) if len(parts) > 1 else parts[0]
    return parts[0]


def _scan_imports(root: Path, sources: list[dict[str, Any]]) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for s in sources[:400]:
        rel = s.get("path") or ""
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:80_000]
        except OSError:
            continue
        lang = s.get("lang") or ""
        if lang == "python" or rel.endswith(".py"):
            for m in _PY_IMPORT.finditer(text):
                mod = m.group(1) or m.group(2) or ""
                if mod:
                    edges.append((rel, mod.split(".")[0] if not mod.startswith(".") else mod))
        elif lang in ("javascript", "typescript") or rel.endswith((".js", ".ts", ".tsx", ".jsx")):
            for m in _JS_IMPORT.finditer(text):
                mod = m.group(1) or m.group(2) or ""
                if mod:
                    edges.append((rel, mod))
    return edges


def _to_mermaid(project: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    def sid(x: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", x)[:48] or "n"

    lines = ["flowchart LR", f"  {sid(project)}[\"{project}\"]"]
    shown = {project}
    # Prefer structural edges
    count = 0
    for e in edges:
        if e.get("rel") == "depends_on":
            continue
        a, b = e.get("from", ""), e.get("to", "")
        if not a or not b:
            continue
        if a not in shown:
            lines.append(f"  {sid(a)}[\"{a}\"]")
            shown.add(a)
        if b not in shown:
            kind = next((n.get("kind") for n in nodes if n.get("id") == b), "")
            shape = f"({b})" if kind == "dependency" else f"[\"{b}\"]"
            lines.append(f"  {sid(b)}{shape}")
            shown.add(b)
        label = e.get("rel") or ""
        lines.append(f"  {sid(a)} -->|{label}| {sid(b)}")
        count += 1
        if count >= 60:
            break
    return "\n".join(lines) + "\n"
