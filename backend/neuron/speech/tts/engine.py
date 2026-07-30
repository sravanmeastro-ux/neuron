"""Phase 7 modular TTS engine — speak / stop_speaking / is_speaking.

Providers (priority):
  1. Piper (neural, local) when configured
  2. System SAPI via pyttsx3 (free Windows voices)
  3. Browser speechSynthesis signal (always available)

Sentence-chunked synthesis gives low latency + interruptibility between chunks.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Iterator

from neuron.speech.tts.base import SpeakResult, TTSProvider
from neuron.speech.tts.browser_provider import BrowserProvider
from neuron.speech.tts.piper_provider import PiperProvider
from neuron.speech.tts.system_provider import SystemProvider

OUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tts_out"
OUT_DIR.mkdir(exist_ok=True)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[;:])\s+")


def _split_chunks(text: str, max_chars: int = 220) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    if not parts:
        parts = [text]
    # Merge tiny fragments; split oversized
    out: list[str] = []
    buf = ""
    for p in parts:
        if len(p) > max_chars:
            if buf:
                out.append(buf)
                buf = ""
            for i in range(0, len(p), max_chars):
                out.append(p[i : i + max_chars].strip())
            continue
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= max_chars:
            buf = f"{buf} {p}"
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


class TTSEngine:
    def __init__(self):
        self._providers: list[TTSProvider] = [
            PiperProvider(),
            SystemProvider(),
            BrowserProvider(),
        ]
        self._lock = threading.RLock()
        self._speaking = False
        self._stop = threading.Event()
        self._current: SpeakResult | None = None
        self._active_provider: TTSProvider | None = None
        self._started_at = 0.0

    def providers_status(self) -> list[dict]:
        return [{"name": p.name, "available": p.available()} for p in self._providers]

    def _pick(self) -> TTSProvider:
        import json
        prefer = ""
        try:
            cfg = json.loads(
                (Path(__file__).resolve().parent.parent.parent.parent / "config.json").read_text(encoding="utf-8")
            ).get("tts") or {}
            prefer = (cfg.get("provider") or "").lower().strip()
        except Exception:
            prefer = ""
        if prefer:
            for p in self._providers:
                if p.name == prefer and p.available():
                    return p
        for p in self._providers:
            if p.available():
                return p
        return self._providers[-1]

    def is_speaking(self) -> bool:
        with self._lock:
            return self._speaking

    def stop_speaking(self) -> dict:
        """Interrupt current speech (server synthesis + signal client)."""
        self._stop.set()
        with self._lock:
            prov = self._active_provider
            self._speaking = False
        if prov is not None:
            try:
                prov.stop()
            except Exception:
                pass
        try:
            from neuron.speech.session import get_session
            get_session().speaking = False
            get_session().request_interrupt()
        except Exception:
            pass
        return {"ok": True, "speaking": False}

    def speak(self, text: str, *, streaming: bool | None = None) -> SpeakResult:
        """Synthesize text. Uses sentence chunks when streaming enabled (default)."""
        text = (text or "").strip()
        if not text:
            return SpeakResult(engine="none", text="")

        import json
        cfg = {}
        try:
            cfg = json.loads(
                (Path(__file__).resolve().parent.parent.parent.parent / "config.json").read_text(encoding="utf-8")
            ).get("tts") or {}
        except Exception:
            pass
        if cfg.get("enabled") is False:
            return SpeakResult(engine="browser", text=text)

        use_stream = streaming if streaming is not None else bool(cfg.get("streaming", True))
        self._stop.clear()
        provider = self._pick()
        with self._lock:
            self._speaking = True
            self._active_provider = provider
            self._started_at = time.time()
        try:
            from neuron.speech.session import get_session
            get_session().speaking = True
            get_session().clear_interrupt()
        except Exception:
            pass

        try:
            if use_stream and provider.name != "browser":
                return self._speak_chunked(provider, text)
            out = OUT_DIR / "last.wav"
            result = provider.synthesize(text, out)
            if result.error and provider.name != "browser":
                # Fall through providers
                for p in self._providers:
                    if p is provider or not p.available():
                        continue
                    result = p.synthesize(text, out)
                    if not result.error or p.name == "browser":
                        break
            self._current = result
            return result
        finally:
            with self._lock:
                self._speaking = False
                self._active_provider = None
            try:
                from neuron.speech.session import get_session
                get_session().speaking = False
            except Exception:
                pass

    def _speak_chunked(self, provider: TTSProvider, text: str) -> SpeakResult:
        """Synthesize sentence chunks (interruptible); merge to last.wav for the client."""
        chunks = _split_chunks(text)
        if not chunks:
            return SpeakResult(engine=provider.name, text=text)
        if len(chunks) == 1:
            out = OUT_DIR / "last.wav"
            part = provider.synthesize(chunks[0], out)
            if part.error:
                for p in self._providers:
                    if p is provider or not p.available():
                        continue
                    whole = p.synthesize(text, out)
                    if not whole.error or p.name == "browser":
                        whole.chunks = 1
                        self._current = whole
                        return whole
            part.chunks = 1
            if part.path and _cfg_play_local():
                _play_wav_interruptible(part.path, self._stop)
                if self._stop.is_set():
                    part.interrupted = True
            self._current = part
            return part

        last = SpeakResult(engine=provider.name, text=text, chunks=0)
        part_paths: list[str] = []
        for i, chunk in enumerate(chunks):
            if self._stop.is_set():
                last.interrupted = True
                break
            out = OUT_DIR / f"chunk_{i}.wav"
            part = provider.synthesize(chunk, out)
            last.engine = part.engine
            last.error = part.error
            last.chunks = i + 1
            if part.error and i == 0:
                for p in self._providers:
                    if p is provider or not p.available():
                        continue
                    whole = p.synthesize(text, OUT_DIR / "last.wav")
                    if not whole.error or p.name == "browser":
                        whole.chunks = 1
                        self._current = whole
                        return whole
            if part.path:
                part_paths.append(part.path)
                if _cfg_play_local():
                    _play_wav_interruptible(part.path, self._stop)
                    if self._stop.is_set():
                        last.interrupted = True
                        break
        merged = OUT_DIR / "last.wav"
        if part_paths and _concat_wavs(part_paths, merged):
            last.path = str(merged)
            last.audio_url = f"/tts_out/{merged.name}"
        elif part_paths:
            last.path = part_paths[0]
            last.audio_url = f"/tts_out/{Path(part_paths[0]).name}"
        self._current = last
        return last

    def speak_stream_events(self, text: str) -> Iterator[dict]:
        """Yield progress events for WS streaming playback."""
        text = (text or "").strip()
        if not text:
            return
        provider = self._pick()
        self._stop.clear()
        with self._lock:
            self._speaking = True
            self._active_provider = provider
        try:
            from neuron.speech.session import get_session
            get_session().speaking = True
        except Exception:
            pass
        try:
            chunks = _split_chunks(text)
            for i, chunk in enumerate(chunks):
                if self._stop.is_set():
                    yield {"type": "tts_interrupted", "index": i}
                    break
                out = OUT_DIR / f"stream_{i}.wav"
                # Also refresh last.wav for simple clients
                part = provider.synthesize(chunk, out)
                if i == 0 and part.path:
                    try:
                        import shutil
                        shutil.copy(part.path, OUT_DIR / "last.wav")
                    except Exception:
                        pass
                yield {
                    "type": "tts_chunk",
                    "index": i,
                    "total": len(chunks),
                    "text": chunk,
                    "engine": part.engine,
                    "audio_url": f"/tts_out/{out.name}" if part.path else None,
                    "error": part.error,
                }
            yield {"type": "tts_done", "interrupted": self._stop.is_set()}
        finally:
            with self._lock:
                self._speaking = False
                self._active_provider = None
            try:
                from neuron.speech.session import get_session
                get_session().speaking = False
            except Exception:
                pass


def _cfg_play_local() -> bool:
    try:
        import json
        cfg = json.loads(
            (Path(__file__).resolve().parent.parent.parent.parent / "config.json").read_text(encoding="utf-8")
        ).get("tts") or {}
        return bool(cfg.get("play_locally", False))
    except Exception:
        return False


def _concat_wavs(paths: list[str], dest: Path) -> bool:
    """Concatenate PCM WAV files (same format) into dest."""
    try:
        import wave
        frames = bytearray()
        params = None
        for p in paths:
            with wave.open(p, "rb") as w:
                if params is None:
                    params = w.getparams()
                elif (
                    w.getnchannels() != params.nchannels
                    or w.getsampwidth() != params.sampwidth
                    or w.getframerate() != params.framerate
                ):
                    continue
                frames.extend(w.readframes(w.getnframes()))
        if not params or not frames:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest), "wb") as out:
            out.setparams(params)
            out.writeframes(bytes(frames))
        return dest.exists() and dest.stat().st_size > 44
    except Exception:
        return False


def _play_wav_interruptible(path: str, stop_event: threading.Event) -> None:
    try:
        import sounddevice as sd
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32")
        sd.play(data, sr)
        while True:
            stream = sd.get_stream()
            if stream is None or not stream.active:
                break
            if stop_event.is_set():
                sd.stop()
                break
            time.sleep(0.05)
        return
    except Exception:
        pass
    try:
        import wave
        import winsound
        duration = 0.5
        try:
            with wave.open(path, "rb") as w:
                duration = max(0.1, w.getnframes() / float(w.getframerate()))
        except Exception:
            pass
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        end = time.time() + duration
        while time.time() < end:
            if stop_event.wait(0.05):
                winsound.PlaySound(None, winsound.SND_PURGE)
                break
    except Exception:
        pass


_ENGINE: TTSEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_tts() -> TTSEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = TTSEngine()
        return _ENGINE


def speak(text: str, **kwargs) -> SpeakResult:
    return get_tts().speak(text, **kwargs)


def stop_speaking() -> dict:
    return get_tts().stop_speaking()


def is_speaking() -> bool:
    return get_tts().is_speaking()


def status() -> str:
    eng = get_tts()
    avail = [p["name"] for p in eng.providers_status() if p["available"]]
    pick = eng._pick().name
    return f"TTS: active={pick}; available={', '.join(avail) or 'none'}"
