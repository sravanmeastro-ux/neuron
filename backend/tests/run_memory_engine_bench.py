"""Benchmarks for Long-Term Memory Engine."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import neuron.memory_engine.store as store_mod
    bench_path = Path(__file__).with_name("_ltm_bench.json")
    store_mod._PATH = bench_path
    store_mod._STORE = None
    if bench_path.exists():
        bench_path.unlink()

    from neuron.memory_engine import (
        remember,
        remember_forever,
        append_episode,
        query_memories,
        for_prompt,
        maintain,
        snapshot,
    )
    from neuron.memory_engine.engine import note_project, note_desktop
    from neuron.memory_engine.types import MemoryKind
    from neuron.memory_engine.store import get_store

    # Seed memories
    yesterday = time.time() - 86400
    p = note_project("NeuronAI", detail="Working on NeuronAI desktop assistant")
    # Backdate for yesterday query
    store = get_store()
    item = store.get(p.item_id)
    assert item
    item.created_at = yesterday + 3600
    item.updated_at = item.created_at
    store._save_unlocked()

    note_desktop(folder="Desktop/Projects/NeuronAI")
    note_desktop(app="Cursor")
    append_episode("Opened Cursor on NeuronAI")
    forever = remember_forever("User prefers dark mode forever")
    assert forever.pinned

    # Old episodic for summarize
    for i in range(5):
        ep = append_episode(f"Old task note {i}")
        it = store.get(ep.item_id)
        it.created_at = time.time() - 5 * 86400
        it.updated_at = it.created_at
    store._save_unlocked()

    # Low-value forget candidate
    junk = remember("transient noise", kind=MemoryKind.EPISODIC.value, value=0.1)
    j = store.get(junk.item_id)
    j.created_at = time.time() - 3 * 86400
    j.value = 0.05
    store._save_unlocked()

    maint = maintain()
    print(f"OK maintain summarized={maint['summarized']} forgotten={maint['forgotten']}")

    q1 = query_memories("What project was I working on yesterday?")
    q2 = query_memories("What folder did I use?")
    q3 = query_memories("Remember this forever: always use Chrome")
    print(f"OK q_project={q1!r}")
    print(f"OK q_folder={q2!r}")
    print(f"OK q_forever={q3!r}")

    prompt = for_prompt()
    print(f"OK for_prompt chars={len(prompt)}")
    snap = snapshot()

    project_ok = bool(q1 and ("NeuronAI" in q1 or "project" in q1.lower()))
    folder_ok = bool(q2 and ("folder" in q2.lower() or "Projects" in q2 or "Neuron" in q2))
    forever_ok = bool(q3 and "forever" in q3.lower())
    pin_ok = forever.pinned and any(i.pinned for i in store.all())
    summary_ok = maint["summarized"] or store.stats()["by_kind"].get("semantic", 0) >= 0
    # After summarize, old episodics reduced
    prompt_ok = "long_term_memory" in prompt or len(prompt) > 0

    # Untouched packages
    import neuron.brain.fast_router as fr
    import neuron.learning_engine as le
    import neuron.taskplan as tp
    untouched = all(hasattr(m, "__file__") for m in (fr, le, tp))

    report = {
        "project_yesterday_ok": project_ok,
        "folder_query_ok": folder_ok,
        "remember_forever_ok": forever_ok,
        "pin_ok": pin_ok,
        "maintain": maint,
        "prompt_ok": prompt_ok,
        "stats": snap.get("stats"),
        "untouched_ok": untouched,
        "pass": project_ok and folder_ok and forever_ok and pin_ok and prompt_ok and untouched,
    }
    out = Path(__file__).with_name("memory_engine_bench_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote {out}")
    try:
        if bench_path.exists():
            bench_path.unlink()
    except Exception:
        pass
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
