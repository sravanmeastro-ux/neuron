# NEURON Electron frontend

Requires the Python brain on `:8765` (`launch-jarvis.bat` or `python backend/server.py`).

```bash
cd frontend
npm install
npm run dev
```

Same WebSocket protocol as the legacy HUD: `stt_status`, `hearing`, `heard`, `response`, `stop_speech`, `confirm`.

Piper audio (when configured) arrives as `audio_url` on `response` messages.
