"""Benchmarks for Project Intelligence."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.project_intelligence import looks_like_project_intelligence, orchestrate, dispatch
    from neuron.project_intelligence.detect import classify_pi_intent
    from neuron.project_intelligence.types import PICapability
    from neuron.project_intelligence.indexer import deep_index, clear_index_cache
    from neuron.project_intelligence.graph import build_project_graph
    from neuron.project_intelligence.bridge import maybe_handle_project_intelligence

    clear_index_cache()

    assert not looks_like_project_intelligence("mute")
    assert not looks_like_project_intelligence("Open Chrome")
    assert looks_like_project_intelligence("What does this project do?")
    assert looks_like_project_intelligence("Where is authentication?")
    assert looks_like_project_intelligence("Find memory leaks.")
    assert looks_like_project_intelligence("Generate project graph")
    print("OK detect")

    assert classify_pi_intent("What does this project do?")["capability"] == PICapability.OVERVIEW.value
    assert classify_pi_intent("Where is authentication?")["capability"] == PICapability.LOCATE.value
    assert classify_pi_intent("Find memory leaks.")["capability"] == PICapability.LEAKS.value
    assert classify_pi_intent("Generate project graph")["capability"] == PICapability.GRAPH.value
    print("OK classify")

    idx = deep_index(str(REPO))
    assert idx.get("source_count", 0) > 0
    assert idx.get("modules")
    print(f"OK index sources={idx.get('source_count')} modules={len(idx.get('modules') or [])} docs={idx.get('doc_count')}")

    g = build_project_graph(str(REPO))
    assert g.get("mermaid") and Path(g["paths"]["mermaid"]).is_file()
    print(f"OK graph nodes={g['stats']['node_count']} edges={g['stats']['edge_count']}")

    say, acted, meta = orchestrate("What does this project do?", root=str(REPO))
    assert acted and meta.get("capability") == PICapability.OVERVIEW.value
    print(f"OK overview say={say[:90]!r}")

    say2, _, meta2 = orchestrate("Where is authentication?", root=str(REPO))
    assert meta2.get("capability") == PICapability.LOCATE.value
    print(f"OK locate say={say2[:90]!r}")

    say3, _, meta3 = orchestrate("Find memory leaks.", root=str(REPO))
    assert meta3.get("capability") == PICapability.LEAKS.value
    print(f"OK leaks say={say3[:90]!r}")

    assert maybe_handle_project_intelligence("mute") is None
    hit = maybe_handle_project_intelligence("What does this project do?")
    assert hit is not None
    print("OK bridge")

    st = dispatch(PICapability.STATUS.value, {"root": str(REPO)})
    assert st.ok
    print(f"OK status {st.say}")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("project_intel_status")
    assert tool_registry.get("project_intel_run")
    print("OK tools")

    print("PASS project_intelligence_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
