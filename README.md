# N.E.U.R.O.N

Local desktop voice AI for Windows. Click the core, speak normally, and NEURON
acts on your PC — apps, browser, files, multi-monitor — then answers out loud.

## Run it

Double-click **`launch-jarvis.bat`** — it opens a 640×480 (4:3) HUD window
(Edge or Chrome, no toolbar).

Then **click the core once** to activate the microphone.

| Core look | Meaning |
|---|---|
| Perfect sphere | Silence / idle |
| Morphing / shaking | It hears you |
| AUDIO INPUT bar | Live speech-to-text |

## Voice loop (V2)

Target pipeline (local / free):

```
wake word → listen → streaming STT → endpoint detection
  → reasoning → execution → TTS
```

**Today (supported):**

1. **Listen** — mic stays open (hands-free by default; optional wake word in `backend/config.json`).
2. **Streaming STT** — local Whisper over the WebSocket PCM stream (Phase 6 pipeline).
3. **Endpoint detection** — utterance gate rejects junk / incomplete fragments.
4. **Reasoning** — rules + local Ollama planner → structured steps.
5. **Execution** — AgentLoop (`Observe → Plan → Act → Verify → Recover`).
6. **TTS** — Piper / system SAPI / browser speech (interruptible chunks).

**Wake word (optional):** set `voice.wake_word_required` true in `backend/config.json`.
Say “Neuron” (or enable openWakeWord) then the command. Conversation mode skips
wake until timeout.

## Interruption (V2)

NEURON can be interrupted **while speaking** and **while running a task**.

Example — NEURON is saying:

> “I found the Blender project and I'm—”

You:

> “Neuron, stop.”

It **stops immediately**: TTS cancels and the AgentLoop aborts before the next step.

### Interrupt phrases

- “Neuron, stop.” / “stop Neuron”
- “stop talking” / “stop speaking” / “be quiet” / “shut up” / “silence”
- “halt” / “abort” / “cancel that” / “never mind”
- Bare “stop.” while it is busy or speaking

Barge-in also triggers when you start talking over it (energy spike while WORKING):
speech cuts off and the current task is marked interrupted.

While a long task is running, new commands are not queued. Say **“Neuron, stop.”**
to cancel, then give the next order.

## Voice commands (the brain)

Examples:

- “open chrome” / “open notepad” / “open spotify”
- “search for weather in delhi” / “search blender on youtube”
- “move chrome to monitor 2”
- “play the newest MrBeast video fullscreen”
- “type hello world” / “press control c”
- “volume up” / “mute” / “pause” / “next song”
- “what time is it” / “who are you”
- “Neuron, stop.” — interrupt speech or task

Domain skills (preferred workflows): `youtube.search`, `windows.move_to_monitor`,
`spotify.play`, `discord.open_channel`, `files.find`, `blender.open_project`, …

## Phase 8 — Safety and permissions

Actions are classified into tiers before they run:

| Tier | Examples | Behavior |
|---|---|---|
| **Safe** | Open Chrome, switch/focus window, scroll, YouTube, screenshots, search files | Runs immediately |
| **Confirmation** | Send/upload wording, modify/create files, type into forms, close apps, computer_use | Asks first — say **confirm** / **yes** / **go ahead**, or **cancel** |
| **High** | Shell / privileged PowerShell (non read-only) | Confirm + extra scrutiny |
| **Blocked** | Shutdown/restart, format/wipe disk, system deletes, financial sends | **Never runs**, even if you say confirm |

Content heuristics elevate a normally-safe click/type when the target looks like
Send / Delete / Upload / Install / Pay.

**Always-on protections (kept):**

- Shutdown and restart stay **disabled** in the brain.
- PyAutoGUI **FAILSAFE** is on — slam the mouse into **any screen corner** to abort input automation.
- Say **“Neuron, stop.”** to interrupt TTS or an in-flight AgentLoop.

Ask “safety status” anytime for the live tier summary.

## Phase 9 — Self-learning (controlled)

NEURON learns **procedures**, not source code. It will not rewrite its own `.py` files.

### Teach by demonstration

You:

> “Neuron, learn how I create a new Blender project.”

Then do the workflow with the mouse (clicks are recorded). When finished:

> “Done.” / “Stop learning.” / “Save the procedure.”

NEURON stores a skill such as:

```
Skill: blender.new_project
1. open Blender
2. wait for startup
3. select General
4. verify viewport
```

### Reuse later

> “Create a Blender project.”

It runs the learned (or built-in) procedure through AgentLoop with verify steps.

Other phrases: “list procedures”, “forget skill blender.new_project”, “teaching status”.

This extends `app_learner` / `click_recorder` / `voice_recipes` — UI knowledge and click capture still work; Phase 9 adds named, reusable **skills** under `backend/learned_procedures.json`.

## Status (V3)

### IMPLEMENTED

- Voice loop: listen → local Whisper STT → endpoint → AgentLoop → TTS
- Interruptions while speaking or acting (“Neuron stop”, barge-in)
- Safety tiers (safe / confirm / high / blocked) + shutdown refuse + PyAutoGUI failsafe
- Domain skills (YouTube, browser, windows, Spotify, Discord, files, Blender)
- Semantic procedure learning (no source rewrites; no passwords/coords by default)
- Multi-monitor NL refs (main / N / other / left / right / foreground) via live geometry
- Multi-app staged plans with per-step verify
- Context engine + reference resolver (deixis) + grounded planner + adaptive recovery
- Reliability benchmark **151** scenarios (plan / mock / live) with measured metrics

### EXPERIMENTAL

- Live multi-monitor placement on unusual layouts (soft-pass when only one display)
- Blender render verify (soft focus check after F12 — not full render-job OCR)
- CapabilityRouter multi-app composer on free-form speech (best with clear “open X on monitor Y” phrasing)
- openWakeWord / conversation-mode wake skipping

### PLANNED

- Broader LIVE-mode certification across more apps (current LIVE is opt-in / start small)
- Richer perception failure injection in LIVE (today covered in unit + mock bench)
- Cloud-free “fully autonomous long-horizon” agent — **not claimed**; NEURON is a local assistant with verify/recover, not a production autopilot

NEURON is **not** declared fully autonomous or production-ready. Rates below are **measured**.

## Reliability benchmark (V3.9 — 151 workflows)

Goal: **>=95% task success on supported benchmark tasks**. Report the actual measured rate even when lower.

```
Task success rate = successful attempts / attempted attempts
Also tracked: step success, recovery success, avg retries, avg completion ms,
planner / perception / execution / verification failure counts
```

| Mode | Behavior |
|------|----------|
| **PLAN** | Scores fixed plans / policy / clarify expectations. **Never** executes desktop tools. |
| **MOCK** | AgentLoop with stubbed tools (+ optional verify-fail injection for recovery). |
| **LIVE** | Real desktop actions; safety tiers still apply. Start with `--ids`. |

From `backend/`:

```bash
# Plan shape + policy (no desktop side effects) — CI-safe
python tests/run_reliability_bench.py --mode plan --repeats 1

# Closed-loop plumbing with stubbed tools
python tests/run_reliability_bench.py --mode mock --repeats 1

# Real desktop — start small
python tests/run_reliability_bench.py --mode live --ids open_chrome,open_notepad --repeats 1

python tests/run_reliability_bench.py --list
python tests/run_v39_hardening_tests.py
```

Catalog covers apps, browser, YouTube, files, windows, multi-monitor, context/multi-turn (TEST A–D), multi-app, skills, recovery, interruptions, ambiguous clarify, safety, planner/perception/verification failures.

Latest measured (this machine, V3.9): see `backend/tests/v39_plan_report.json` and `v39_mock_report.json`.

## The reasoning brain (local AI)

Beyond fixed commands, a local LLM (Ollama) turns requests into tool steps,
verifies results, and retries / replans on failure.

- 100% local (private, no cloud API cost for the brain).
- Model in `backend/config.json` (e.g. `llama3`).
- Memory scopes: **working** (current task), **session** (this run),
  **persistent** (allowlisted facts only).
- Honest failures instead of pretending success.

Smarter model later: `ollama pull qwen2.5:14b`, then set `"model": "qwen2.5:14b"`.

## Files

- `index.html` / `css/style.css` / `js/app.js` — HUD, mic, barge-in, voice replies
- `backend/server.py` — FastAPI + WebSocket; STT → brain → TTS; interrupt routing
- `backend/brain.py` — command entry + escape hatches (stop, wake, monitors, confirm)
- `backend/neuron/brain/` — AgentLoop, planner, verifier, ComputerState, Element Resolver
- `backend/neuron/v3/` — ContextEngine, ReferenceResolver, Perception, ToolRegistry, GroundedPlanner, multi-app, loop types
- `backend/neuron/speech/` — wake, endpoint, pipeline, TTS, interrupt
- `backend/neuron/safety/` — Phase 8 tiers, confirm queue, failsafe
- `backend/neuron/learning/` — semantic procedure learning
- `backend/neuron/skills/` — domain skill workflows
- `backend/tests/reliability/` — 151-task reliability bench (plan / mock / live)
- `backend/docs/V3_FINAL_REPORT.md` — V3 integration final report
- `backend/learned_procedures.json` — saved user-taught procedures (not source)
- `backend/actions.py` — keyboard/mouse/app helpers
- `requirements.txt` — Python deps (installed by the launcher)

## Privacy

STT (Whisper), LLM (Ollama), OCR, and TTS stay on your machine unless you
point a tool at the open web on purpose (browser / search). Learned skills
scrub passwords/tokens and do not store pixel crops by default (`click_record.store_pixels=false`).
