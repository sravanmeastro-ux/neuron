"""Benchmarks for Workflow Recording — vars, loops, conditions, edit, dry replay."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import neuron.workflows.store as store_mod
    from neuron.workflows import editor, replay, recorder
    from neuron.workflows.types import Workflow, WorkflowStep
    from neuron.workflows.vars import eval_condition, substitute

    bench = Path(tempfile.gettempdir()) / "neuron_workflow_bench.json"
    store_mod._STORE = bench
    if bench.exists():
        bench.unlink()

    # Variables
    assert substitute("Hello {{name}}", {"name": "NEURON"}) == "Hello NEURON"
    assert eval_condition("{{n}} == 3", {"n": 3})
    assert not eval_condition("{{n}} > 5", {"n": 3})
    assert eval_condition("true", {})
    print("OK vars/conditions")

    # Create workflow with loop + if + set
    wf = editor.create_blank(
        "bench-demo",
        variables={"name": "World", "n": 2, "flag": "yes"},
    )
    steps = [
        {"kind": "set", "args": {"name": "greet", "value": "Hello {{name}}"}},
        {
            "kind": "loop",
            "args": {"count": "{{n}}", "as": "i"},
            "steps": [
                {"kind": "wait", "args": {"ms": 1}},
                {"kind": "set", "args": {"name": "last_i", "value": "{{i}}"}},
            ],
        },
        {
            "kind": "if",
            "args": {"when": "{{flag}} == yes"},
            "steps": [{"kind": "set", "args": {"name": "branch", "value": "then"}}],
            "else_steps": [{"kind": "set", "args": {"name": "branch", "value": "else"}}],
        },
        {"kind": "type", "args": {"text": "{{greet}}"}},
        {"kind": "wait", "args": {"ms": 5}},
    ]
    wf = editor.replace_steps(wf.id, steps)
    assert wf and len(wf.steps) == 5
    print(f"OK edit steps={len(wf.steps)} version={wf.version}")

    # Dry replay (no OS side effects for type — dry_run skips)
    r = replay.replay(wf, dry_run=True)
    assert r.get("ok"), r
    assert r["variables"].get("branch") == "then"
    assert str(r["variables"].get("last_i")) in ("1", "1.0") or r["variables"].get("last_i") == 1
    print(f"OK dry_replay vars={ {k: r['variables'][k] for k in ('greet','branch','last_i') if k in r['variables']} }")

    # Editor: add_loop / add_condition / variables
    wf2 = editor.create_blank("bench-edit")
    editor.insert_step(wf2.id, 0, {"kind": "wait", "args": {"ms": 1}})
    editor.add_loop(wf2.id, index=1, count=3, body=[{"kind": "wait", "args": {"ms": 1}}])
    editor.add_condition(
        wf2.id,
        index=0,
        when="{{x}} == 1",
        then_steps=[{"kind": "set", "args": {"name": "ok", "value": 1}}],
    )
    editor.set_variables(wf2.id, {"x": 1})
    detail = editor.get_detail(wf2.id)
    assert detail and detail["variables"]["x"] == 1
    assert any(s["kind"] == "loop" for s in detail["steps"])
    assert any(s["kind"] == "if" for s in detail["steps"])
    print("OK editor loops/conditions")

    # Real wait-only replay (safe)
    wait_wf = Workflow(
        id="wait-only",
        name="wait-only",
        steps=[WorkflowStep(kind="wait", args={"ms": 10})],
    )
    store_mod.save(wait_wf)
    r2 = replay.replay(wait_wf, dry_run=False)
    assert r2.get("ok"), r2
    print("OK wait replay")

    # Recorder status API (don't leave recording on)
    st = recorder.status()
    assert "recording" in st
    print(f"OK recorder status recording={st['recording']}")

    # Tool registration
    from neuron.brain import tool_registry

    tool_registry.ensure_bootstrapped()
    for name in ("workflow_record", "workflow_list", "workflow_run", "workflow_edit"):
        assert tool_registry.get(name), name
    print("OK tool_registry workflow_*")

    listed = editor.list_all()
    assert len(listed) >= 2
    print(f"OK list n={len(listed)}")

    print("PASS workflow_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
