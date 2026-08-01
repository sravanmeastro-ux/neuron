"""Benchmarks for Developer Mode (no destructive build/test execute by default)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.developer import looks_like_developer, orchestrate, dispatch
    from neuron.developer.detect import classify_dev_intent
    from neuron.developer.types import DevCapability
    from neuron.developer import analyze, deps, git_ops, index as index_mod, build_test, refactor
    from neuron.developer.bridge import maybe_handle_developer

    assert not looks_like_developer("mute")
    assert not looks_like_developer("Open Chrome")
    assert looks_like_developer("Create a React app.")
    assert looks_like_developer("Fix this compile error.")
    assert looks_like_developer("Review my latest commit.")
    assert looks_like_developer("Run the unit tests.")
    assert looks_like_developer("Explain this stack trace.")
    assert looks_like_developer("Find the bug.")
    print("OK detect")

    # Index this repo
    idx = index_mod.index_project(REPO)
    assert idx.file_count > 0
    print(f"OK index name={idx.name} langs={idx.languages} files={idx.file_count}")

    graph = deps.dependency_graph(str(REPO))
    print(f"OK deps nodes={graph['node_count']} edges={graph['edge_count']}")

    # Diagnostics / bugs / explain
    trace = '''Traceback (most recent call last):
  File "app.py", line 10, in main
    foo()
  File "app.py", line 4, in foo
    return 1/0
ZeroDivisionError: division by zero'''
    diag = analyze.parse_diagnostics(trace)
    assert diag["count"] >= 1
    bugs = analyze.localize_bug(trace, str(REPO))
    assert bugs["suspects"]
    expl = analyze.explain_code_or_trace(trace)
    assert "ZeroDivision" in expl["explanation"] or "python" in expl["explanation"].lower()
    print(f"OK diagnostics/bugs/explain primary={diag.get('primary', {}).get('kind')}")

    # Build/test detect (no execute)
    b = build_test.detect_build_commands(str(REPO))
    t = build_test.detect_test_commands(str(REPO))
    print(f"OK build_cmds={len(b.get('commands') or [])} test_cmds={len(t.get('commands') or [])}")

    # Git review
    rev = git_ops.git_show_latest(str(REPO))
    print(f"OK git_review ok={rev.get('ok')} subject={rev.get('subject', '')[:50]!r}")

    # Refactor / scaffold / docs
    ref = refactor.refactor_suggestions("Refactor this class", str(REPO))
    assert ref["suggestions"]
    sc = refactor.scaffold_plan("Create a React app.")
    assert sc["kind"] == "react"
    docs = refactor.docs_outline(str(REPO))
    assert "# " in docs["markdown"]
    print("OK refactor/scaffold/docs")

    # Orchestrate
    say, acted, meta = orchestrate("Index the project", root=str(REPO))
    assert acted and meta.get("capability") == DevCapability.INDEX.value
    print(f"OK orchestrate index say={say[:70]!r}")

    say2, _, meta2 = orchestrate("Review my latest commit.", root=str(REPO))
    assert meta2.get("capability") == DevCapability.GIT.value
    print(f"OK orchestrate review say={say2[:70]!r}")

    assert classify_dev_intent("Run the unit tests.")["capability"] == DevCapability.TEST.value
    assert maybe_handle_developer("mute") is None
    hit = maybe_handle_developer("Analyze the project")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    for name in ("developer_status", "developer_run", "developer_index", "developer_review"):
        assert tool_registry.get(name), name
    print("OK tools")

    print("PASS developer_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
