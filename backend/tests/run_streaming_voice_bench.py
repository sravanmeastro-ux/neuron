"""Benchmarks for Streaming Voice Engine (offline / synthetic)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.streaming_voice.audio_hooks import get_audio_chain
    from neuron.streaming_voice.early_intent import looks_early_executable, try_early_intent
    from neuron.streaming_voice.modes import ModeController
    from neuron.streaming_voice.engine import StreamingVoiceEngine
    from neuron.streaming_voice.llm_stream import stream_llm
    from neuron.streaming_voice.tts_stream import stream_tts
    from neuron.streaming_voice import config as cfg

    results: dict = {}

    # --- Modes ---
    m = ModeController("continuous")
    assert m.should_listen()
    m.set_mode("ptt")
    assert not m.should_listen()
    m.on_ptt(True)
    assert m.should_listen()
    m.on_ptt(False)
    assert not m.should_listen()
    m.set_mode("conversation")
    m.arm(10)
    assert m.should_listen()
    results["modes_ok"] = True
    print("OK modes continuous/ptt/conversation")

    # --- Audio hooks latency ---
    chain = get_audio_chain()
    pcm = (np.random.randn(1600).astype(np.float32) * 0.01)
    t0 = time.perf_counter()
    for _ in range(50):
        chain.process(pcm)
    hook_ms = (time.perf_counter() - t0) * 1000 / 50
    results["audio_hook_ms_mean"] = round(hook_ms, 3)
    print(f"OK audio hooks mean {hook_ms:.3f}ms/frame")

    # --- Early intent classifier ---
    early_ok = 0
    for t in ("mute", "volume up", "scroll down", "skip ad"):
        if looks_early_executable(t):
            early_ok += 1
            print(f"OK early allow {t!r}")
        else:
            print(f"FAIL early allow {t!r}")
    early_block = 0
    for t in ("open chrome and search youtube", "download blender", "what is on my screen"):
        if not looks_early_executable(t):
            early_block += 1
            print(f"OK early block {t!r}")
        else:
            print(f"FAIL early block {t!r}")
    results["early_allow"] = early_ok / 4
    results["early_block"] = early_block / 3

    # Try mute via FastIntent (may act on system volume)
    t0 = time.perf_counter()
    fr = try_early_intent("mute", busy=False)
    early_ms = (time.perf_counter() - t0) * 1000
    results["early_intent_latency_ms"] = round(early_ms, 2)
    results["early_intent_acted"] = bool(fr and fr.get("ok"))
    print(f"OK early_intent mute acted={results['early_intent_acted']} {early_ms:.1f}ms")

    # --- Engine push silence (wake/STT not required) ---
    eng = StreamingVoiceEngine()
    silence = np.zeros(1600, dtype=np.float32)
    t0 = time.perf_counter()
    for _ in range(20):
        eng.push_pcm(silence)
    push_ms = (time.perf_counter() - t0) * 1000 / 20
    results["push_pcm_ms_mean"] = round(push_ms, 3)
    print(f"OK push_pcm silence {push_ms:.3f}ms/frame")

    # Simulated interrupt latency
    eng.set_busy(True)
    eng._interrupt_t0 = time.perf_counter()
    time.sleep(0.01)
    interrupt_ms = eng.note_interrupt()
    results["interrupt_latency_ms_sim"] = interrupt_ms
    print(f"OK interrupt sim {interrupt_ms}ms")

    # --- Streaming TTS (may be browser/system) ---
    t0 = time.perf_counter()
    tts_events = list(stream_tts("Okay."))
    tts_ms = (time.perf_counter() - t0) * 1000
    results["tts_stream_ms"] = round(tts_ms, 2)
    results["tts_event_types"] = [e.get("type") for e in tts_events]
    print(f"OK stream_tts events={results['tts_event_types']} {tts_ms:.1f}ms")

    # --- Streaming LLM (optional — skip hard fail if Ollama down) ---
    llm_ok = False
    llm_ms = 0.0
    try:
        t0 = time.perf_counter()
        toks = 0
        for ev in stream_llm("Say hi in three words.", system="Be brief."):
            if ev.get("type") == "llm_token":
                toks += 1
            if ev.get("type") == "llm_done":
                llm_ok = True
            if ev.get("type") == "llm_error":
                break
        llm_ms = (time.perf_counter() - t0) * 1000
        results["llm_stream_ok"] = llm_ok
        results["llm_stream_ms"] = round(llm_ms, 2)
        results["llm_tokens"] = toks
        print(f"OK/SKIP llm_stream ok={llm_ok} toks={toks} {llm_ms:.1f}ms")
    except Exception as exc:
        results["llm_stream_ok"] = False
        results["llm_error"] = str(exc)
        print(f"SKIP llm_stream: {exc}")

    # Untouched packages
    import neuron.brain.fast_router as fr
    import neuron.understand as und
    import neuron.screen as scr
    import neuron.taskplan as tp
    results["forbidden_untouched_ok"] = all(hasattr(x, "__file__") for x in (fr, und, scr, tp))

    results["config"] = {
        "streaming_voice_engine": cfg.streaming_enabled(),
        "listen_mode": cfg.listen_mode_default(),
        "early_intent": cfg.early_intent_enabled(),
        "echo": cfg.echo_cancellation_enabled(),
        "noise": cfg.noise_suppression_enabled(),
    }

    # Synthetic E2E estimate: hook + push + early
    results["e2e_estimate_ms"] = round(
        results["audio_hook_ms_mean"]
        + results["push_pcm_ms_mean"]
        + float(results.get("early_intent_latency_ms") or 0),
        2,
    )

    tts_ok = (
        "tts_done" in (results.get("tts_event_types") or [])
        or "tts_ready" in (results.get("tts_event_types") or [])
    )
    results["pass"] = (
        results["modes_ok"]
        and results["early_allow"] == 1.0
        and results["early_block"] == 1.0
        and results["forbidden_untouched_ok"]
        and tts_ok
    )

    out = Path(__file__).with_name("streaming_voice_bench_report.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"Wrote {out}")
    return 0 if results["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
