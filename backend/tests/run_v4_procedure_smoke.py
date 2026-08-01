"""V4.9 procedure smoke — MOCK / read-only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from neuron.v4.learn import (
        build_trace,
        reset_procedure_registry,
        get_procedure_learner,
        learn_metrics,
        procedure_learning_enabled,
    )
    from neuron.v4.learn.execute import expand_procedure_plan, extract_procedure_params
    from neuron.v4.capability import reset_capability_catalog, get_capability_catalog
    from neuron.v4.plan import HierarchicalPlanner, reset_hierarchical_planner

    print("V4.9 procedure smoke (MOCK / no live control)")
    print(f"procedure_learning_enabled={procedure_learning_enabled()} (default false)")

    reg = reset_procedure_registry(clear_store=True)
    learner = get_procedure_learner()

    def steps(q, mon=2):
        return [
            {"tool": "windows.open_app", "arguments": {"name": "Chrome"}, "verification": "SUCCESS"},
            {"tool": "windows.move_to_monitor", "arguments": {"monitor": mon}, "verification": "SUCCESS"},
            {"tool": "youtube.search", "arguments": {"query": q}, "verification": "SUCCESS"},
        ]

    for q in ("Blender tutorials", "Unreal Engine tutorials", "Python tutorials"):
        ok, msg, cand = learner.ingest_trace(
            build_trace(
                goal_text=f"Open YouTube on monitor 2 and search {q}",
                steps=steps(q),
                final_status="SUCCESS",
                task_verified=True,
                intent_family="youtube_search",
            )
        )
        print(f"  ingest {q!r}: {ok} {msg} evidence={getattr(cand,'evidence_count',0)}")

    from neuron.v4.learn.generalize import generalize_traces
    cand = generalize_traces(learner.traces)
    assert cand and "query" in [p.name for p in cand.parameters]
    print("CANDIDATE:", cand.name, "params=", [p.name for p in cand.parameters])

    aok, areason, proc = reg.accept_and_register(cand, force=True)
    assert aok and proc, areason
    print("REGISTERED:", proc.procedure_id, "v", proc.version)

    reset_capability_catalog()
    reg.sync_catalog()
    cat = get_capability_catalog()
    cap = cat.get(proc.procedure_id)
    print("CATALOG:", cap.capability_id if cap else None, cap.kind.value if cap else None)
    assert cap is not None

    proc.confidence = 0.9
    proc.aliases = list(proc.aliases) + ["do my youtube search workflow"]
    learner.definitions[proc.procedure_id] = proc

    params = extract_procedure_params(
        "Do my YouTube search workflow on monitor 1 for Rust tutorials",
        proc,
    )
    print("PARAMS:", params)
    plan = expand_procedure_plan(proc, params)
    print("PLAN steps:", [s.get("action") for s in plan["steps"]])

    reset_hierarchical_planner()
    tp = HierarchicalPlanner().create_plan(
        "Do my YouTube search workflow on monitor 1 for Rust tutorials"
    )
    print("PLANNER source=", tp.source, "subgoals=", len(tp.subgoals))
    assert tp.source == "learned_procedure"

    # Mock verification success on expanded steps
    for s in plan["steps"]:
        cat.note_outcome(s["action"], exec_ok=True, verify="SUCCESS", intent="procedure")
    print("VERIFY: mock SUCCESS on all steps")

    m = learn_metrics()
    print(
        f"PROCEDURE_DUPLICATE_COUNT={m['PROCEDURE_DUPLICATE_COUNT']} "
        f"PROCEDURE_PRIVACY_VIOLATION_COUNT={m['PROCEDURE_PRIVACY_VIOLATION_COUNT']}"
    )
    assert m["PROCEDURE_DUPLICATE_COUNT"] == 0
    assert m["PROCEDURE_PRIVACY_VIOLATION_COUNT"] == 0
    print("\nProcedure smoke PASS")


if __name__ == "__main__":
    main()
