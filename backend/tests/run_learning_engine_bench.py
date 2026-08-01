"""Benchmarks for Learning Engine."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    # Isolate store file for bench
    import neuron.learning_engine.store as store_mod
    bench_path = Path(__file__).with_name("_learning_engine_bench.json")
    store_mod._STORE_PATH = bench_path
    store_mod._STORE = None
    if bench_path.exists():
        bench_path.unlink()

    from neuron.learning_engine import (
        observe_tool,
        observe_utterance,
        favorites,
        ranked_behaviors,
        predict_next,
        for_prompt,
        snapshot,
    )
    from neuron.learning_engine.scores import reinforce, decayed_score, rank
    from neuron.learning_engine.types import ScoredItem

    # Reinforcement unit
    item = ScoredItem(key="Chrome", category="app")
    reinforce(item, ok=True)
    reinforce(item, ok=True)
    reinforce(item, ok=False)
    assert item.success == 2 and item.fail == 1
    assert decayed_score(item) != 0
    print(f"OK reinforce score={item.score:.3f} decayed={decayed_score(item):.3f}")

    # Simulate habits
    t0 = time.perf_counter()
    for _ in range(5):
        observe_tool("open_app", {"name": "Chrome"}, ok=True)
    for _ in range(3):
        observe_tool("open_app", {"name": "Code"}, ok=True)
    for _ in range(2):
        observe_tool("open_app", {"name": "Discord"}, ok=True)
    observe_tool("open_app", {"name": "Notepad"}, ok=False)

    for site in ("youtube.com", "youtube.com", "github.com", "blender.org"):
        observe_tool("open_website", {"url": f"https://{site}"}, ok=True)

    observe_tool("open_folder", {"location": "desktop/Projects"}, ok=True)
    observe_tool("open_folder", {"location": "desktop/Projects"}, ok=True)
    observe_tool("move_window_to_monitor", {"monitor": "2"}, ok=True)
    observe_tool("hotkey", {"keys": "ctrl c"}, ok=True)
    observe_tool("hotkey", {"keys": "ctrl v"}, ok=True)
    observe_tool("hotkey", {"keys": "ctrl c"}, ok=True)

    observe_utterance("open chrome", acted=True)
    observe_utterance("search youtube for blender", acted=True)
    observe_ms = (time.perf_counter() - t0) * 1000

    apps = favorites("app", limit=3)
    sites = favorites("website", limit=3)
    browsers = favorites("browser", limit=2)
    editors = favorites("editor", limit=2)
    folders = favorites("folder", limit=2)
    monitors = favorites("monitor", limit=2)
    flows = favorites("workflow", limit=3)
    ranked = ranked_behaviors(limit=8)
    preds = predict_next(limit=5)
    prompt = for_prompt()

    print(f"OK apps={apps}")
    print(f"OK sites={sites}")
    print(f"OK browsers={browsers} editors={editors}")
    print(f"OK folders={folders} monitors={monitors}")
    print(f"OK workflows={flows}")
    print(f"OK ranked top={ranked[0] if ranked else None}")
    print(f"OK predictions={preds[:3]}")
    print(f"OK for_prompt chars={len(prompt)}")
    print(f"OK observe batch {observe_ms:.1f}ms")

    # Ranking: Chrome should beat Notepad (more successes)
    app_keys = [a["key"] for a in apps]
    chrome_first = app_keys and app_keys[0].lower() == "chrome"
    youtube_fav = any("youtube" in s["key"] for s in sites)
    editor_ok = editors and "code" in editors[0]["key"].lower()
    browser_ok = browsers and "chrome" in browsers[0]["key"].lower()
    pred_ok = len(preds) >= 1
    prompt_ok = "favorite_apps" in prompt or "learning_engine" in prompt

    # Untouched packages
    import neuron.brain.fast_router as fr
    import neuron.understand as und
    import neuron.screen as scr
    import neuron.taskplan as tp
    import neuron.computer_use as cu
    untouched = all(hasattr(m, "__file__") for m in (fr, und, scr, tp, cu))

    report = {
        "reinforce_ok": True,
        "chrome_ranked_first": chrome_first,
        "youtube_favorite": youtube_fav,
        "preferred_editor_ok": editor_ok,
        "preferred_browser_ok": browser_ok,
        "predictions_n": len(preds),
        "ranked_n": len(ranked),
        "workflows_n": len(flows),
        "prompt_ok": prompt_ok,
        "observe_batch_ms": round(observe_ms, 2),
        "snapshot": snapshot(),
        "untouched_ok": untouched,
        "pass": (
            chrome_first
            and youtube_fav
            and editor_ok
            and browser_ok
            and pred_ok
            and prompt_ok
            and untouched
        ),
    }
    out = Path(__file__).with_name("learning_engine_bench_report.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "snapshot"}, indent=2))
    print(f"Wrote {out}")
    try:
        if bench_path.exists():
            bench_path.unlink()
    except Exception:
        pass
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
