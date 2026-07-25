# N.E.U.R.O.N — Frontend

Iron Man style desktop AI frontend: a small 4:3 window with a glowing energy
core that stays a perfect sphere when silent, then morphs and shakes when it
hears your voice, plus live speech-to-text.

## Run it

Double-click **`launch-jarvis.bat`** — it opens a 640x480 (4:3) app window
using Edge (or Chrome), with no browser toolbar.

Then **click the core once** to activate the microphone.

- Perfect sphere = silence
- Morphing / shaking core = it hears you
- Your words appear live in the AUDIO INPUT bar at the bottom

## Voice commands (the brain)

The backend brain listens to everything you say and acts on commands like:

- "open chrome" / "open notepad" / "open spotify" / "open website youtube.com"
- "search for weather in delhi"
- "type hello world" / "press enter" / "press control c"
- "click" / "double click" / "right click" / "move mouse up" / "scroll down"
- "volume up" / "mute" / "pause" / "next song"
- "close window" / "minimize" / "maximize" / "switch window" / "show desktop"
- "take a screenshot" / "lock my computer"
- "what time is it" / "who are you"

Anything that isn't a command is ignored. Shutdown/restart are disabled
for safety. Emergency stop: slam the mouse into any screen corner.

## The reasoning brain (local AI)

Beyond the fixed commands, NEURON has a local LLM brain (via Ollama) that
handles anything else you say — it turns your request into a sequence of
actions and runs them, then replies in a JARVIS-style voice.

- Runs 100% locally through Ollama (private, no cloud, no API cost).
- Model configured in `backend/config.json` (currently `llama3`).
- Remembers facts across sessions (`backend/memory_store.json`).
- For common file tasks it uses reliable built-in actions; for anything
  else it can run PowerShell — and honestly reports failures instead of
  pretending success.

To use a smarter model later: `ollama pull qwen2.5:14b`, then set
`"model": "qwen2.5:14b"` in `backend/config.json`.

## Files

- `index.html` — HUD layout
- `css/style.css` — Iron Man / N.E.U.R.O.N styling (glow, grid, scanline)
- `js/app.js` — blob animation, speech recognition, brain connection, voice replies
- `backend/server.py` — local server (FastAPI + WebSocket), serves the frontend
- `backend/brain.py` — interprets your sentences into actions
- `backend/actions.py` — keyboard/mouse/app control (pyautogui)
- `requirements.txt` — Python dependencies (installed automatically by the launcher)
