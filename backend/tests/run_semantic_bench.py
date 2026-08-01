"""Semantic understanding accuracy + latency benchmarks."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from neuron.understand import understand, context_mem


# (utterance, expected_substr in rewritten, expected_intent_prefix_or_exact)
CASES = [
    ("Open Chrome", "open chrome", "OPEN_APPLICATION"),
    ("Open the browser.", "open chrome", "OPEN_APPLICATION"),
    ("Can you launch Chrome?", "open chrome", "OPEN_APPLICATION"),
    ("I need Google.", "open google", "OPEN"),
    ("Let's browse.", "open chrome", "OPEN_APPLICATION"),
    ("Open YouTube.", "open youtube", "OPEN_WEBSITE"),
    ("Take me to YouTube.", "open youtube", "OPEN_WEBSITE"),
    ("Search for Blender tutorials.", "search", "SEARCH"),
    ("volume up", "volume up", "VOLUME"),
    ("mute", "mute", "VOLUME"),
    ("summarize this document", None, "COMPLEX"),  # should NOT force desktop
]

ENTITY_CASES = [
    ("Open Blender", {"application": "blender"}),
    ("Search YouTube for Unreal Engine", {"website": "youtube", "query": "unreal engine"}),
    ("Move Chrome to monitor 2", {"application": "chrome", "monitor": "2"}),
]


def main() -> int:
    intent_ok = 0
    rewrite_ok = 0
    latencies = []
    false_positives = []
    details = []

    for utt, expect_sub, expect_intent in CASES:
        u = understand(utt, refresh_desktop=False)
        latencies.append(u.latency_ms)
        intent_hit = u.intent_id.startswith(expect_intent) if expect_intent else True
        if expect_intent == "COMPLEX":
            intent_hit = u.intent_id == "COMPLEX" or u.band == "low"
            # False positive = treating complex as high-confidence desktop
            if u.band == "high" and u.intent_id not in ("COMPLEX", "UNKNOWN"):
                false_positives.append(utt)
        else:
            if not intent_hit:
                # soft: rewrite may still be correct
                pass
        sub_hit = True
        if expect_sub:
            sub_hit = expect_sub.lower() in (u.rewritten or "").lower()
        if intent_hit:
            intent_ok += 1
        if sub_hit:
            rewrite_ok += 1
        details.append({
            "utt": utt,
            "rewritten": u.rewritten,
            "intent": u.intent_id,
            "conf": round(u.confidence, 3),
            "band": u.band,
            "ms": round(u.latency_ms, 2),
            "intent_ok": intent_hit,
            "rewrite_ok": sub_hit,
            "entities": [{"kind": e.kind, "value": e.value} for e in u.entities],
        })
        print(
            f"{'OK' if intent_hit and sub_hit else '~~'} {utt!r:42s} -> "
            f"{u.rewritten!r:36s} {u.intent_id:16s} {u.confidence:.2f} {u.latency_ms:.2f}ms"
        )

    # Entity accuracy
    ent_ok = 0
    ent_total = 0
    for utt, expect in ENTITY_CASES:
        u = understand(utt, refresh_desktop=False)
        got = {e.kind: e.value for e in u.entities}
        hit = all(got.get(k) == v or (v in str(got.get(k, "")).lower()) for k, v in expect.items())
        ent_total += 1
        if hit:
            ent_ok += 1
        print(f"{'OK' if hit else 'FAIL'} entities {utt!r} expect={expect} got={got}")

    # Chain: open youtube then search
    context_mem.remember_success(
        rewritten="open youtube", intent_id="OPEN_WEBSITE", user="open youtube"
    )
    context_mem.get_memory().last_website = "youtube"
    chained = understand("Search for Blender tutorials.", refresh_desktop=False)
    chain_ok = "youtube" in chained.rewritten.lower()
    print(f"{'OK' if chain_ok else 'FAIL'} chain -> {chained.rewritten!r} ctx={chained.context_used}")

    # Deixis
    context_mem.get_memory().current_app = "chrome"
    deix = understand("close that", refresh_desktop=False)
    deix_ok = "chrome" in deix.rewritten.lower()
    print(f"{'OK' if deix_ok else 'FAIL'} deixis -> {deix.rewritten!r}")

    # Fast path still works + semantic overhead
    from neuron.brain.fast_router import try_handle
    t0 = time.perf_counter()
    fr = try_handle("volume up")
    fast_ms = (time.perf_counter() - t0) * 1000
    exec_ok = bool(fr and fr.ok and not fr.used_agent_loop)

    n = len(CASES)
    report = {
        "intent_accuracy": round(intent_ok / n, 3),
        "rewrite_accuracy": round(rewrite_ok / n, 3),
        "entity_accuracy": round(ent_ok / max(1, ent_total), 3),
        "false_positives": false_positives,
        "chain_ok": chain_ok,
        "deixis_ok": deix_ok,
        "fast_router_still_ok": exec_ok,
        "fast_router_ms": round(fast_ms, 2),
        "understanding_latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 2),
            "max": round(max(latencies), 2),
            "min": round(min(latencies), 2),
        },
        "details": details,
        "pass": (
            intent_ok / n >= 0.8
            and rewrite_ok / n >= 0.8
            and ent_ok == ent_total
            and chain_ok
            and deix_ok
            and exec_ok
            and not false_positives
            and (sum(latencies) / len(latencies)) < 50.0
        ),
    }
    out = Path(__file__).resolve().parent / "semantic_bench_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "details"}, indent=2))
    print(f"Wrote {out}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
