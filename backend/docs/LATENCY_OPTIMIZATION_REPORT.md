# NEURON Latency Optimization — Final Report

Date: 2026-08-01  
Scope: Incremental hot-path optimizations (no AgentLoop rewrite, hierarchical voice stays LEGACY).

## 1. Files modified

| File | Why |
|------|-----|
| `backend/neuron/perf.py` | **New** — PhaseTimer, thread-local timer, log level gate, JSONL recorder |
| `backend/neuron/speech/pipeline.py` | vad_ms/stt_ms meta; busy skips partials; try_lock partials |
| `backend/stt.py` | `try_transcribe_partial` (non-blocking) |
| `backend/server.py` | Wire perf timer; pipeline busy flag; text response **before** TTS |
| `js/app.js` | Handle `tts_ready` after early `response` |
| `backend/neuron/perception/ocr.py` | Process-wide RapidOCR singleton |
| `backend/neuron/perception/pipeline.py` | Reuse OpenAI VLM client |
| `backend/neuron/windows/state.py` | TTL cache windows/processes/monitors + invalidate |
| `backend/neuron/windows/apps.py` | Shorter wait (4s default); invalidate on open/focus |
| `backend/brain.py` | Skip glance for fast desktop; volume/media short-circuit |
| `backend/neuron/brain/agent.py` | Soft `wait_seconds=3` on capability open_app; act timing; log gate |
| `backend/config.json` | VAD 320+100ms; partial interval 1.2s; `logging.level` |
| `launch-jarvis.bat` | faster-whisper only (drop openai-whisper install) |
| `backend/tests/run_perf_baseline.py` | **New** harness |
| `backend/tests/perf_baseline_report.json` | Measured samples |

## 2. Before vs after architecture

**Unchanged:** Mic → WS → VoicePipeline → faster-whisper → brain → CapabilityRouter → AgentLoop → tools → TTS.

**Changed on hot path:**
- Volume/mute/media → **bypass AgentLoop** (like skip-ad)
- Fast desktop intents → **skip screen glance**
- Response text → client **immediately**; TTS follows (`tts_ready`)
- Partials yield to finals (busy + non-blocking lock)

## 3. Measured gains (brain path, no STT)

From `tests/run_perf_baseline.py` (this machine):

| Command | Before (audit est.) | After | Notes |
|---------|---------------------|-------|-------|
| mute | hundreds of ms–seconds via AgentLoop | **~42 ms** | fast_volume_media |
| volume up/down | same | **~210 ms** | media keys |
| open chrome (running) | ~1.9–4.2 s | **~1.5 s** | glance=0; focus ~0.76s + verify |
| open notepad (cold) | multi-second | ~7.4 s | still AgentLoop observe×N |
| window list (cached) | 50–500 ms each | **~0 ms** hit / ~250 ms cold | 350ms TTL |

## 4. Startup / CPU / GPU / memory

- **Startup:** Interactive HTTP still ~3s bat wait; STT warm remains lazy CUDA load (not &lt;3s model-ready). Bat no longer installs openai-whisper.
- **CPU:** Fewer UIA/psutil polls via TTL cache; fewer always-on prints when `logging.level` ≥ INFO (agent uses gate).
- **GPU:** Partials less frequent (1.2s) and skipped while busy; finals less contended.
- **Memory:** One RapidOCR + one VLM client (was re-allocating every call).

## 5. Voice latency (config)

| Knob | Old | New |
|------|-----|-----|
| silence_ms | 480 | **320** |
| hangover_ms | 180 | **100** |
| VAD floor | ~660 ms | **~420 ms** |
| partial interval | 0.85 s | **1.2 s** |

STT engine: faster-whisper `small` / CUDA / float16 (unchanged this pass). True streaming ASR not implemented (by plan).

## 6. Remaining bottlenecks

1. AgentLoop observe/verify still dominates open/focus (~1–7s)  
2. Focus UNCERTAIN cases can still hit multi-second paths  
3. Cold Whisper load 30–90s on first use  
4. Electron HUD still has no mic  
5. LLM path still up to 18s when CapabilityRouter misses  

## 7. Recommended next steps

1. Lightweight verify mode for capability open/focus (skip redundant UIA walks)  
2. Optional PTT UI control (mute already exists server-side)  
3. Phase-instrumented LIVE voice soak with STT+VAD phases filled  
4. Consider `tiny`/`base` model option for &lt;300ms STT on weak GPUs  

## 8. How to re-measure

```bat
cd backend
python tests/run_perf_baseline.py
python tests/run_perf_baseline.py --live
```

JSONL: `backend/tests/perf_latency.jsonl`  
Report: `backend/tests/perf_baseline_report.json`
