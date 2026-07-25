"""N.E.U.R.O.N backend server.

Serves the frontend and exposes a WebSocket at /ws.
The frontend streams microphone PCM; local Whisper turns it into text;
the brain interprets and acts.
"""

import asyncio
import json
import re
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import brain
import brain_llm
import stt

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="N.E.U.R.O.N")

_STOP_RE = re.compile(
    r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron)\b",
    re.I,
)


def _is_stop_talk(text: str) -> bool:
    return bool(_STOP_RE.search(text or ""))


@app.on_event("startup")
async def _startup():
    async def keep_warm_llm():
        while True:
            await asyncio.to_thread(brain_llm.warmup)
            await asyncio.sleep(240)

    async def warm_stt():
        try:
            # Load Whisper before clients connect so the UI does not fall back
            # to Windows / browser speech recognition.
            print("[server] warming OpenAI Whisper (may take a minute)…", flush=True)
            msg = await asyncio.to_thread(stt.get_engine().warmup)
            print(f"[server] {msg}", flush=True)
        except Exception as exc:
            print(f"[server] Whisper warmup failed: {exc}", flush=True)

    if brain_llm.is_enabled():
        asyncio.create_task(keep_warm_llm())
    if stt.get_engine().is_enabled():
        # Don't block HTTP/WS on Whisper load — UI must show BRAIN: ONLINE fast.
        asyncio.create_task(warm_stt())

    # Watch active windows and learn how apps work as they open / gain focus.
    try:
        import app_watch
        app_watch.start_watcher()
    except Exception as exc:
        print(f"[server] auto_learn watcher failed: {exc}", flush=True)

    # Load any previous PC inventory so open_app knows installed app names.
    try:
        import pc_trainer
        pc_trainer.bootstrap_on_startup()
    except Exception as exc:
        print(f"[server] pc_trainer bootstrap failed: {exc}", flush=True)


async def _run_command(websocket: WebSocket, text: str, busy_state: dict):
    """Execute one command and reply. busy_state is a shared mutable dict."""
    now = asyncio.get_event_loop().time()
    norm = " ".join(text.lower().split())

    # Stop talking always wins — even mid-task / mid-speech.
    if _is_stop_talk(text):
        busy_state["busy"] = False
        await websocket.send_text(json.dumps({
            "type": "stop_speech",
            "heard": text,
            "text": "Okay.",
            "acted": True,
        }))
        return

    if busy_state["busy"]:
        await websocket.send_text(json.dumps({
            "type": "response",
            "heard": text,
            "text": "One moment — still finishing the last request.",
            "acted": False,
        }))
        return

    if norm == busy_state["last_text"] and (now - busy_state["last_at"]) < 8.0:
        await websocket.send_text(json.dumps({
            "type": "response",
            "heard": text,
            "text": None,
            "acted": False,
        }))
        return

    busy_state["last_text"] = norm
    busy_state["last_at"] = now
    busy_state["busy"] = True
    try:
        reply, acted = await asyncio.to_thread(brain.handle_command, text)
    except Exception as exc:
        reply, acted = f"That failed: {exc}", False
    finally:
        busy_state["busy"] = False

    if reply == "__STOP_SPEECH__":
        await websocket.send_text(json.dumps({
            "type": "stop_speech",
            "heard": text,
            "text": "Okay.",
            "acted": True,
        }))
        return

    await websocket.send_text(json.dumps({
        "type": "response",
        "heard": text,
        "text": reply,
        "acted": acted,
    }))


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    busy_state = {"busy": False, "last_text": "", "last_at": 0.0}
    assembler = stt.UtteranceAssembler()
    engine = stt.get_engine()
    use_whisper = engine.is_enabled()

    await websocket.send_text(json.dumps({
        "type": "stt_status",
        "engine": "whisper" if use_whisper else "browser",
        "backend": engine.backend_name() if use_whisper else "browser",
        "ready": False,
    }))

    # Tell the client when Whisper finishes loading (may already be warm).
    async def notify_ready():
        try:
            msg = await asyncio.to_thread(engine.warmup)
            print(f"[server] {msg}", flush=True)
            await websocket.send_text(json.dumps({
                "type": "stt_status",
                "engine": "whisper",
                "backend": engine.backend_name(),
                "ready": True,
            }))
        except Exception as exc:
            await websocket.send_text(json.dumps({
                "type": "stt_status",
                "engine": "browser",
                "ready": False,
                "error": str(exc),
            }))

    if use_whisper:
        asyncio.create_task(notify_ready())

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # ---- binary: Int16 LE PCM @ 16 kHz mono --------------------
            if "bytes" in message and message["bytes"] is not None:
                if not use_whisper:
                    continue
                raw = message["bytes"]
                if len(raw) < 2:
                    continue
                pcm_i16 = np.frombuffer(raw, dtype=np.int16)
                pcm = (pcm_i16.astype(np.float32) / 32768.0)

                level = assembler.level(pcm)
                # Lightweight hearing cue for the blob (not a transcript yet).
                if level > 0.08 and not assembler._muted:
                    await websocket.send_text(json.dumps({
                        "type": "hearing",
                        "level": round(level, 3),
                    }))

                clip = assembler.push(pcm)
                if clip is None:
                    continue

                await websocket.send_text(json.dumps({
                    "type": "status",
                    "text": "TRANSCRIBING...",
                }))

                text = await asyncio.to_thread(engine.transcribe, clip)
                if not text:
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "text": "LISTENING",
                    }))
                    continue

                await websocket.send_text(json.dumps({
                    "type": "heard",
                    "text": text,
                }))
                await _run_command(websocket, text, busy_state)
                continue

            # ---- text JSON control / fallback transcript ---------------
            raw_text = message.get("text")
            if not raw_text:
                continue
            try:
                msg = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")

            if mtype == "control":
                if "mute" in msg:
                    assembler.set_muted(bool(msg["mute"]))
                continue

            if mtype == "transcript":
                # Manual / browser-fallback path.
                text = (msg.get("text") or "").strip()
                if text:
                    await _run_command(websocket, text, busy_state)
                continue

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[ws] closed: {exc}", flush=True)


# Serve index.html, css/, js/ from the project root (mounted last so /ws wins)
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
