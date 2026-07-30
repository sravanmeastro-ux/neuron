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

## Reliability benchmark (~100 desktop workflows)

Goal: **~100 real workflows at >=95% success**, not thousands of flaky one-offs.

```
Task success rate = successful completed attempts / attempted attempts
```

From `backend/`:

```bash
# Plan shape only (no desktop side effects) — CI-safe
python tests/run_reliability_bench.py --mode plan --repeats 5

# Closed-loop plumbing with stubbed tools
python tests/run_reliability_bench.py --mode mock --tag core --repeats 3

# Real desktop — start small; confirm-tier tools auto-confirm in the bench
python tests/run_reliability_bench.py --mode live --ids open_chrome,open_notepad,type_hello --repeats 3

# List catalog / filter
python tests/run_reliability_bench.py --list
python tests/run_reliability_bench.py --list --tag core
```

Catalog covers open/focus apps, YouTube search/play 1st/2nd, Discord↔Chrome, move to monitor 2 (soft-pass on single-monitor PCs), Downloads/find file, Calculator, type/copy/paste, scroll/UI click, popup Escape, wrong-focus recovery, compound workflows, and safety refuse-shutdown.

JSON report: `backend/tests/reliability_report.json`.

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
- `backend/neuron/speech/` — wake, endpoint, pipeline, TTS, interrupt
- `backend/neuron/safety/` — Phase 8 tiers, confirm queue, failsafe
- `backend/neuron/learning/` — **Phase 9 procedure learning** (demonstration → skill)
- `backend/neuron/skills/` — domain skill workflows (youtube, windows, …)
- `backend/tests/reliability/` — ~100-task reliability bench (plan / mock / live)
- `backend/learned_procedures.json` — saved user-taught procedures (not source)
- `backend/actions.py` — keyboard/mouse/app helpers
- `requirements.txt` — Python deps (installed by the launcher)

## Privacy

STT (Whisper), LLM (Ollama), OCR, and TTS stay on your machine unless you
point a tool at the open web on purpose (browser / search).
