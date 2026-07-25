"""Benchmark local models as NEURON's reasoning brain.

For each model, feed natural spoken requests through the real planning prompt
and score whether the plan contains the right action with the right args.

Run:  python tests/bench_planner.py [model1] [model2] ...
Default models: current config model + candidates that are installed.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import brain_llm  # noqa: E402


def step_has(data, action, args_subset=None):
    for step in data.get("steps", []) or []:
        if (step.get("action") or "").strip() != action:
            continue
        if args_subset:
            args = step.get("args", {}) or {}
            if not all(str(args.get(k)) == str(v) for k, v in args_subset.items()):
                continue
        return True
    return False


# Each case: (request, scorer(data) -> bool, description)
CASES = [
    ("play the second video on the youtube homepage",
     lambda d: step_has(d, "youtube_home_play", {"index": 2})
     or step_has(d, "play_result", {"index": 2}),
     "youtube_home_play index=2"),

    ("skip the ad",
     lambda d: step_has(d, "skip_ad")
     and not step_has(d, "youtube_home_play") and not step_has(d, "play_result"),
     "skip_ad only"),

    ("skip the add in the youtube",
     lambda d: step_has(d, "skip_ad")
     and not step_has(d, "youtube_home_play") and not step_has(d, "play_result"),
     "skip_ad despite mishear"),

    ("open notepad and type hello from neuron",
     lambda d: step_has(d, "open_app") and step_has(d, "type_text"),
     "open_app + type_text"),

    ("play despacito",
     lambda d: step_has(d, "search_site") or step_has(d, "youtube_search")
     or (step_has(d, "open_website") and step_has(d, "play_result")),
     "search youtube for song"),

    ("search for wireless headphones on amazon",
     lambda d: step_has(d, "search_site"),
     "search_site amazon"),

    ("create a folder called projects on my desktop",
     lambda d: step_has(d, "create_folder"),
     "create_folder"),

    ("make the volume louder",
     lambda d: step_has(d, "volume"),
     "volume"),

    ("what's my battery level",
     lambda d: step_has(d, "system_report") or step_has(d, "run_shell"),
     "system_report"),

    ("open youtube and play the third video",
     lambda d: step_has(d, "youtube_home_play", {"index": 3})
     or step_has(d, "play_result", {"index": 3}),
     "chained play index=3"),

    ("write a short poem about iron man in notepad",
     lambda d: step_has(d, "open_app") and step_has(d, "type_text"),
     "creative: open notepad + type poem"),

    ("close this window",
     lambda d: step_has(d, "window", {"action": "close"}) or step_has(d, "press_keys"),
     "window close"),

    ("take a screenshot",
     lambda d: step_has(d, "screenshot"),
     "screenshot"),

    ("how is the weather in mumbai",
     lambda d: step_has(d, "search_web") or step_has(d, "search_site")
     or step_has(d, "open_website"),
     "web lookup"),

    ("hello how are you today",
     lambda d: not (d.get("steps") or []),
     "conversation: no steps"),
]


def bench(model):
    wins, total_ms = 0, 0.0
    rows = []
    for request, scorer, desc in CASES:
        t0 = time.time()
        data = brain_llm.plan(request, model=model) or {}
        ms = (time.time() - t0) * 1000
        total_ms += ms
        try:
            ok = bool(scorer(data))
        except Exception:
            ok = False
        wins += ok
        rows.append((ok, ms, desc, data.get("steps")))
    return wins, total_ms / len(CASES), rows


def main():
    models = sys.argv[1:] or ["llama3", "qwen2.5vl:7b"]
    print(f"Benchmarking {len(CASES)} cases on: {', '.join(models)}\n")
    summary = []
    for model in models:
        print(f"--- {model} ---")
        wins, avg_ms, rows = bench(model)
        for ok, ms, desc, steps in rows:
            mark = "PASS" if ok else "FAIL"
            print(f"  {mark} [{ms:6.0f}ms] {desc}")
            if not ok:
                print(f"        steps={json.dumps(steps)[:150]}")
        print(f"  => {wins}/{len(CASES)} correct, avg {avg_ms:.0f}ms\n")
        summary.append((model, wins, avg_ms))

    print("=== SUMMARY ===")
    for model, wins, avg_ms in summary:
        print(f"{model:20s} {wins:2d}/{len(CASES)}  avg {avg_ms:.0f}ms")


if __name__ == "__main__":
    main()
