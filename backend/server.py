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


def _is_stop_talk(text: str) -> bool:
    try:
        from neuron.speech.interrupt import is_stop_phrase
        return is_stop_phrase(text)
    except Exception:
        return bool(re.search(
            r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron|"
            r"(?:hey\s+)?neuron[,.]?\s+stop|^stop[.!]?$)\b",
            text or "",
            re.I,
        ))


def _is_skip_ad_cmd(text: str) -> bool:
    """Priority voice command — must interrupt long AgentLoop work."""
    return bool(re.search(
        r"\b(skip|close|dismiss)\b.{0,24}\b(ad|ads|add|adds|sad)\b"
        r"|\b(ad|ads|add|adds|sad)\b.{0,16}\b(skip|close|dismiss)\b"
        r"|\bskip(?:ping)?(?:\s+the|\s+this|\s+that)?\s+(?:ad|ads|add|adds|sad)\b",
        text or "",
        re.I,
    ))


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

    # Hands-free: no wake word; remember full PC access.
    try:
        import voice_mode
        voice_mode.bootstrap_hands_free()
        print(f"[server] voice: {voice_mode.status()}", flush=True)
    except Exception as exc:
        print(f"[server] voice_mode bootstrap failed: {exc}", flush=True)

    try:
        from neuron.safety.failsafe import ensure_failsafe
        print(f"[server] {ensure_failsafe()}", flush=True)
    except Exception as exc:
        print(f"[server] failsafe init failed: {exc}", flush=True)

    try:
        from neuron.memory import store as sql
        sql.init_db()
        print("[server] SQLite memory ready", flush=True)
    except Exception as exc:
        print(f"[server] sqlite memory failed: {exc}", flush=True)

    try:
        from neuron.speech import tts_piper
        print(f"[server] {tts_piper.status()}", flush=True)
    except Exception as exc:
        print(f"[server] tts status failed: {exc}", flush=True)


async def _run_command(websocket: WebSocket, text: str, busy_state: dict):
    """Execute one command and reply. busy_state is a shared mutable dict."""
    now = asyncio.get_event_loop().time()
    norm = " ".join(text.lower().split())

    # Stop / interrupt always wins — even mid-task / mid-speech.
    if _is_stop_talk(text):
        busy_state["busy"] = False
        busy_state.pop("pending_override", None)
        try:
            from neuron.speech.interrupt import request as request_interrupt
            request_interrupt(reason=f"phrase:{text!r}")
        except Exception:
            try:
                from neuron.speech.tts import stop_speaking
                stop_speaking()
            except Exception:
                pass
        await websocket.send_text(json.dumps({
            "type": "stop_speech",
            "heard": text,
            "text": "Okay.",
            "acted": True,
            "interrupted": True,
        }))
        return

    if busy_state["busy"]:
        # Skip-ad must interrupt long AgentLoop/scroll thrash — queue override.
        if _is_skip_ad_cmd(text):
            busy_state["pending_override"] = text
            try:
                from neuron.speech.interrupt import request as request_interrupt
                request_interrupt(reason="skip_ad_override")
            except Exception:
                pass
            await websocket.send_text(json.dumps({
                "type": "response",
                "heard": text,
                "text": "Got it — skipping the ad.",
                "acted": True,
            }))
            return
        # Non-stop speech while working — do not queue; wait for interrupt phrase.
        await websocket.send_text(json.dumps({
            "type": "response",
            "heard": text,
            "text": "Still working — say 'Neuron, stop' to interrupt, or 'skip the ad'.",
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

    # Optional wake-word gate (OFF by default — hands-free).
    try:
        import voice_mode
        if not voice_mode.allow_transcript(text):
            await websocket.send_text(json.dumps({
                "type": "response",
                "heard": text,
                "text": None,
                "acted": False,
            }))
            return
    except Exception:
        pass

    busy_state["last_text"] = norm
    busy_state["last_at"] = now
    busy_state["busy"] = True
    busy_state["barge_sent"] = False
    try:
        from neuron.speech.interrupt import clear as clear_interrupt
        clear_interrupt()
    except Exception:
        pass
    try:
        reply, acted = await asyncio.to_thread(brain.handle_command, text)
        # If interrupted mid-run, prefer a short ack over a stale success line.
        try:
            from neuron.speech.interrupt import interrupted
            if interrupted():
                reply = "Stopped."
                acted = True
        except Exception:
            pass
    except Exception as exc:
        reply, acted = f"That failed: {exc}", False
    finally:
        busy_state["busy"] = False
        busy_state["barge_sent"] = False
        try:
            from neuron.speech.interrupt import clear as clear_interrupt
            clear_interrupt()
        except Exception:
            pass

    override = busy_state.pop("pending_override", None)
    # If we interrupted to honor skip-ad, don't TTS a stale "Stopped."
    if not (override and reply == "Stopped."):
        await _send_command_response(websocket, text, reply, acted)

    if override:
        await _run_command(websocket, override, busy_state)


async def _send_command_response(websocket: WebSocket, text: str, reply, acted: bool):
    """TTS + websocket payload (split out so override can reuse)."""
    # Original body after brain.handle_command lived inline — keep behavior.

    if reply == "__STOP_SPEECH__":
        try:
            from neuron.speech.interrupt import request as request_interrupt
            request_interrupt(reason="brain_stop")
        except Exception:
            try:
                from neuron.speech.tts import stop_speaking
                stop_speaking()
            except Exception:
                pass
        await websocket.send_text(json.dumps({
            "type": "stop_speech",
            "heard": text,
            "text": "Okay.",
            "acted": True,
            "interrupted": True,
        }))
        return

    # Pending confirm notice
    try:
        from neuron.safety import policy
        pending = policy.get_pending()
        if pending and reply and "confirm" in (reply or "").lower():
            await websocket.send_text(json.dumps({
                "type": "confirm",
                "heard": text,
                "action": pending.get("action"),
                "args": pending.get("args") or {},
                "reason": pending.get("reason") or reply,
                "text": reply,
                "acted": True,
            }))
            return
    except Exception:
        pass

    # Phase 7 modular TTS (Piper → system SAPI → browser)
    audio_path = None
    tts_engine_name = "browser"
    if reply and acted:
        try:
            from neuron.speech.tts import speak as tts_speak
            spoken = await asyncio.to_thread(tts_speak, reply)
            tts_engine_name = spoken.engine or "browser"
            if spoken.path:
                audio_path = spoken.path
            # Optional streaming chunks to client
            if spoken.chunks > 1:
                await websocket.send_text(json.dumps({
                    "type": "tts_info",
                    "chunks": spoken.chunks,
                    "engine": tts_engine_name,
                    "interrupted": spoken.interrupted,
                }))
        except Exception:
            try:
                from neuron.speech import tts_piper
                spoken = await asyncio.to_thread(tts_piper.speak_to_file, reply)
                tts_engine_name = spoken.get("engine") or "browser"
                if tts_engine_name == "piper":
                    audio_path = spoken.get("path")
            except Exception:
                pass

    payload = {
        "type": "response",
        "heard": text,
        "text": reply,
        "acted": acted,
        "tts_engine": tts_engine_name,
        "speaking": False,
    }
    if audio_path:
        payload["audio_path"] = audio_path
        try:
            from pathlib import Path
            name = Path(audio_path).name
            payload["audio_url"] = f"/tts_out/{name}"
        except Exception:
            pass

    await websocket.send_text(json.dumps(payload))


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    busy_state = {"busy": False, "last_text": "", "last_at": 0.0, "barge_sent": False}
    engine = stt.get_engine()
    use_whisper = engine.is_enabled()

    # Phase 6 voice pipeline (VAD → partial ASR → endpoint → gate)
    try:
        from neuron.speech.pipeline import VoicePipeline
        from neuron.speech.session import get_session
        voice_pipe = VoicePipeline(get_session())
        assembler = voice_pipe.assembler  # for mute control compat
    except Exception as exc:
        print(f"[ws] voice pipeline fallback: {exc}", flush=True)
        voice_pipe = None
        assembler = stt.UtteranceAssembler()

    await websocket.send_text(json.dumps({
        "type": "stt_status",
        "engine": "whisper" if use_whisper else "browser",
        "backend": engine.backend_name() if use_whisper else "browser",
        "ready": False,
        "phase": 6,
    }))

    async def notify_ready():
        try:
            msg = await asyncio.to_thread(engine.warmup)
            print(f"[server] {msg}", flush=True)
            await websocket.send_text(json.dumps({
                "type": "stt_status",
                "engine": "whisper",
                "backend": engine.backend_name(),
                "ready": True,
                "phase": 6,
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

                if voice_pipe is not None:
                    events = await asyncio.to_thread(voice_pipe.push_pcm, pcm)
                    for ev in events:
                        if ev.kind == "level" and ev.level > 0.08:
                            # Barge-in: new speech while busy → interrupt TTS + task (once)
                            if busy_state["busy"] and ev.level > 0.25 and not busy_state.get("barge_sent"):
                                busy_state["barge_sent"] = True
                                try:
                                    from neuron.speech.interrupt import request as request_interrupt
                                    request_interrupt(reason="barge_in_energy")
                                except Exception:
                                    try:
                                        from neuron.speech.session import get_session
                                        get_session().request_interrupt()
                                    except Exception:
                                        pass
                                    try:
                                        from neuron.speech.tts import stop_speaking
                                        stop_speaking()
                                    except Exception:
                                        pass
                                await websocket.send_text(json.dumps({
                                    "type": "stop_speech",
                                    "heard": "",
                                    "text": None,
                                    "acted": True,
                                    "barge_in": True,
                                    "interrupted": True,
                                }))
                            await websocket.send_text(json.dumps({
                                "type": "hearing",
                                "level": round(ev.level, 3),
                            }))
                        elif ev.kind == "partial" and ev.text:
                            await websocket.send_text(json.dumps({
                                "type": "partial",
                                "text": ev.text,
                            }))
                        elif ev.kind == "wake":
                            await websocket.send_text(json.dumps({
                                "type": "wake",
                                "text": ev.text or "Neuron",
                                "source": (ev.meta or {}).get("source"),
                            }))
                            await websocket.send_text(json.dumps({
                                "type": "status",
                                "text": "LISTENING",
                            }))
                        elif ev.kind == "rejected":
                            await websocket.send_text(json.dumps({
                                "type": "status",
                                "text": "LISTENING",
                                "rejected": (ev.meta or {}).get("reason"),
                                "heard": ev.text or "",
                            }))
                        elif ev.kind == "final" and ev.text:
                            await websocket.send_text(json.dumps({
                                "type": "status",
                                "text": "THINKING...",
                            }))
                            await websocket.send_text(json.dumps({
                                "type": "heard",
                                "text": ev.text,
                            }))
                            # Interruptible: stop phrase always handled in _run_command
                            await _run_command(websocket, ev.text, busy_state)
                    continue

                # Legacy assembler path
                level = assembler.level(pcm)
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
                    if voice_pipe is not None:
                        voice_pipe.set_muted(bool(msg["mute"]))
                    else:
                        assembler.set_muted(bool(msg["mute"]))
                if msg.get("conversation_mode") is not None:
                    try:
                        import voice_mode
                        reply = voice_mode.set_conversation_mode(bool(msg["conversation_mode"]))
                        await websocket.send_text(json.dumps({
                            "type": "response",
                            "text": reply,
                            "acted": True,
                        }))
                    except Exception:
                        pass
                continue

            if mtype == "transcript":
                # Manual / browser-fallback path (still gate + endpoint clean).
                text = (msg.get("text") or "").strip()
                if text:
                    try:
                        from neuron.speech.endpoint import is_complete_command
                        gate = is_complete_command(text)
                        if not gate.accept:
                            continue
                        text = gate.text
                    except Exception:
                        pass
                    await _run_command(websocket, text, busy_state)
                continue

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[ws] closed: {exc}", flush=True)


# Serve Piper WAV output + frontend static (mounted last so /ws wins)
_TTS_DIR = Path(__file__).resolve().parent / "tts_out"
_TTS_DIR.mkdir(exist_ok=True)
app.mount("/tts_out", StaticFiles(directory=str(_TTS_DIR)), name="tts_out")
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
