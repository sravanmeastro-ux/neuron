"""Project Intelligence orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.developer.index import resolve_root
from neuron.project_intelligence import graph as graph_mod
from neuron.project_intelligence import memory as memory_mod
from neuron.project_intelligence import query as query_mod
from neuron.project_intelligence.detect import classify_pi_intent
from neuron.project_intelligence.indexer import deep_index
from neuron.project_intelligence.types import PICapability, PIResult


def dispatch(capability: str, args: dict[str, Any] | None = None) -> PIResult:
    args = args or {}
    root = args.get("root") or args.get("repo")

    if capability == PICapability.STATUS.value:
        root_p = resolve_root(root)
        mem = memory_mod.load_memory(root_p)
        return PIResult(
            ok=True,
            say=(
                f"Project Intelligence online. Root={root_p}; "
                f"memory={'yes' if mem else 'none'}."
            ),
            capability=capability,
            data={"root": str(root_p), "has_memory": bool(mem)},
        )

    if capability == PICapability.INDEX.value:
        idx = deep_index(root)
        mem = memory_mod.remember_project(root)
        say = (
            f"Indexed {idx.get('name')}: {idx.get('source_count')} sources, "
            f"{idx.get('folder_count')} folders, {idx.get('asset_count')} assets, "
            f"{idx.get('doc_count')} docs, {idx.get('build_dir_count')} build dirs. "
            f"Memory -> {mem.get('memory_path')}."
        )
        return PIResult(ok=True, say=say, acted=True, capability=capability, data={"index": idx, "memory": mem})

    if capability == PICapability.OVERVIEW.value:
        data = query_mod.project_overview(root)
        return PIResult(ok=True, say=data.get("say") or "", capability=capability, data=data)

    if capability == PICapability.LOCATE.value:
        data = query_mod.locate_feature(root, topic=str(args.get("topic") or "authentication"))
        return PIResult(ok=True, say=data.get("say") or "", capability=capability, data=data)

    if capability == PICapability.LEAKS.value:
        data = query_mod.find_memory_leaks(root)
        return PIResult(ok=True, say=data.get("say") or "", capability=capability, data=data)

    if capability == PICapability.GRAPH.value:
        data = graph_mod.build_project_graph(root)
        say = (
            f"Project graph: {data.get('stats', {}).get('node_count')} nodes, "
            f"{data.get('stats', {}).get('edge_count')} edges -> "
            f"{(data.get('paths') or {}).get('mermaid')}."
        )
        return PIResult(ok=True, say=say, acted=True, capability=capability, data=data)

    if capability == PICapability.ARCHITECTURE.value:
        mem = memory_mod.remember_project(root)
        arch = mem.get("architecture") or {}
        mods = ", ".join(m.get("module", "") for m in (mem.get("modules") or [])[:8])
        say = (
            f"Architecture remembered for {arch.get('title')}. "
            f"Modules: {mods}. Relationships: {len(mem.get('relationships') or [])}. "
            f"Saved {mem.get('memory_path')}."
        )
        return PIResult(ok=True, say=say, acted=True, capability=capability, data=mem)

    if capability == PICapability.SEARCH.value:
        data = query_mod.search_project(root, query=str(args.get("query") or ""))
        return PIResult(
            ok=bool(data.get("ok")),
            say=data.get("say") or "",
            capability=capability,
            data=data,
            error="" if data.get("ok") else data.get("say") or "",
        )

    return PIResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False, root: str | None = None) -> tuple[str, bool, dict]:
    intent = classify_pi_intent(text)
    cap = intent.get("capability") or PICapability.OVERVIEW.value
    args = dict(intent.get("args") or {})
    if root:
        args["root"] = root
    result = dispatch(cap, args)
    meta = {
        "path": "project_intelligence",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Project intelligence failed.", True, meta
