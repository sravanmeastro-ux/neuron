"""Speech-to-text for N.E.U.R.O.N — local faster-whisper only.

Frontend (or native mic) streams 16 kHz mono Int16/float PCM; energy VAD cuts
utterances. Partial transcription is available for live captions — execution
only happens after endpointing + completeness gate (Phase 6).
"""

from __future__ import annotations

import json
import os
import site
import threading
import time
from pathlib import Path

import numpy as np

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

SAMPLE_RATE = 16000


def _add_cuda_dll_dirs():
    """Make pip-installed NVIDIA CUDA DLLs visible to ctranslate2 on Windows."""
    roots = []
    try:
        roots.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    subdirs = (
        ("nvidia", "cublas", "bin"),
        ("nvidia", "cudnn", "bin"),
        ("nvidia", "cuda_runtime", "bin"),
        ("nvidia", "cuda_nvrtc", "bin"),
    )
    for root in roots:
        for parts in subdirs:
            p = Path(root, *parts)
            if not p.is_dir():
                continue
            os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(p))
                except Exception:
                    pass


_add_cuda_dll_dirs()


def _load_stt_cfg() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return cfg.get("stt", {}) or {}
    except Exception:
        return {}


def _clean_transcript(text: str) -> str:
    try:
        from neuron.speech.endpoint import clean_transcript
        return clean_transcript(text)
    except Exception:
        text = (text or "").strip()
        if not text:
            return ""
        low = text.lower().strip(" .")
        junk = {
            "thank you", "thanks for watching", "subscribe", "you",
            "thank you for watching", "mbc 뉴스", "www", "subtitle",
            "subtitles by", "amara.org", ".",
        }
        if low in junk or len(low) < 2:
            return ""
        return text


def _normalize_model_name(name: str) -> str:
    n = (name or "small").strip().lower()
    aliases = {
        "whisper-1": "small",
        "openai": "small",
        "turbo": "large-v3-turbo",
        "large-v3-turbo": "large-v3-turbo",
        "large_v3_turbo": "large-v3-turbo",
        "large": "large-v3",
        "large-v3": "large-v3",
        "large-v2": "large-v2",
        "medium": "medium",
        "small": "small",
        "base": "base",
        "tiny": "tiny",
    }
    return aliases.get(n, n)


class WhisperEngine:
    """Local STT via faster-whisper (CTranslate2) — not openai-whisper."""

    def __init__(self):
        self._fw_model = None
        self._lock = threading.Lock()
        self._cfg = _load_stt_cfg()
        self._ready = False
        self._err = None
        self._backend = None
        self._device = "cpu"
        self._model_name = "small"

    def is_enabled(self) -> bool:
        return bool(self._cfg.get("enabled", True))

    def backend_name(self) -> str:
        return self._backend or "faster-whisper"

    def status_report(self) -> str:
        self._ensure_model()
        if not self._ready:
            return (
                "Speech recognition isn't ready yet. "
                f"{self._err or 'Still loading faster-whisper.'}"
            )
        return (
            f"I'm using faster-whisper, model {self._model_name}, "
            f"on {self._device}. Not OpenAI Whisper Python and not Windows Speech."
        )

    def warmup(self) -> str:
        self._ensure_model()
        if not self._ready:
            raise RuntimeError(self._err or "faster-whisper failed to load")
        silence = np.zeros(SAMPLE_RATE // 4, dtype=np.float32)
        _ = self.transcribe(silence)
        return f"Whisper ready ({self._backend} {self._model_name} on {self._device})."

    def _ensure_model(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self._cfg = _load_stt_cfg()
            want = (self._cfg.get("device") or "cuda").lower()
            if self._try_faster_whisper(want):
                return
            self._ready = False
            self._err = self._err or "Could not load faster-whisper"

    def _try_faster_whisper(self, want_device: str) -> bool:
        try:
            _add_cuda_dll_dirs()
            from faster_whisper import WhisperModel
        except Exception as exc:
            self._err = f"faster-whisper import failed: {exc}"
            print(f"[stt] {self._err}", flush=True)
            return False

        model_name = _normalize_model_name(self._cfg.get("model", "small"))
        device = "cuda" if want_device.startswith("cuda") else "cpu"
        compute = self._cfg.get(
            "compute_type",
            "float16" if device == "cuda" else "int8",
        )
        try:
            print(
                f"[stt] loading faster-whisper '{model_name}' "
                f"device={device} compute_type={compute}…",
                flush=True,
            )
            self._fw_model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute,
            )
            list(self._fw_model.transcribe(
                np.zeros(SAMPLE_RATE // 8, dtype=np.float32),
                language="en",
                vad_filter=False,
            ))
        except Exception as cuda_exc:
            print(
                f"[stt] faster-whisper {device}/{compute} failed ({cuda_exc}); "
                f"trying CPU int8",
                flush=True,
            )
            try:
                self._fw_model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                )
                device = "cpu"
                compute = "int8"
            except Exception as exc:
                self._err = str(exc)
                print(f"[stt] faster-whisper load failed: {exc}", flush=True)
                return False

        self._model_name = model_name
        self._device = device
        self._backend = "faster-whisper"
        self._ready = True
        self._err = None
        print(
            f"[stt] faster-whisper ready ({model_name} / {device} / {compute})",
            flush=True,
        )
        return True

    def _prep_audio(self, audio: np.ndarray) -> np.ndarray | None:
        if audio is None or len(audio) < SAMPLE_RATE * 0.15:
            return None
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak < 1e-4:
            return None
        if peak > 0:
            audio = audio / max(peak, 0.08)
            audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
        return audio

    def transcribe(self, audio: np.ndarray) -> str:
        """Final transcription of a completed utterance."""
        self._ensure_model()
        audio = self._prep_audio(audio)
        if not self._ready or audio is None:
            return ""
        with self._lock:
            text = self._transcribe_faster(audio, vad=True)
        return _clean_transcript(text)

    def try_transcribe_partial(self, audio: np.ndarray) -> str:
        """Non-blocking partial — returns '' if the model lock is held by a final."""
        self._ensure_model()
        audio = self._prep_audio(audio)
        if not self._ready or audio is None:
            return ""
        if not self._lock.acquire(blocking=False):
            return ""
        try:
            text = self._transcribe_faster(audio, vad=False, beam=1)
        finally:
            self._lock.release()
        return _clean_transcript(text)

    def transcribe_partial(self, audio: np.ndarray) -> str:
        """Fast partial transcript for live captions — never used to execute."""
        self._ensure_model()
        audio = self._prep_audio(audio)
        if not self._ready or audio is None:
            return ""
        with self._lock:
            text = self._transcribe_faster(audio, vad=False, beam=1)
        return _clean_transcript(text)

    def _transcribe_faster(
        self,
        audio: np.ndarray,
        *,
        vad: bool = True,
        beam: int | None = None,
    ) -> str:
        beam = int(beam if beam is not None else self._cfg.get("beam_size", 1))
        segments, _info = self._fw_model.transcribe(
            audio,
            language=self._cfg.get("language", "en"),
            beam_size=beam,
            best_of=beam,
            vad_filter=vad,
            vad_parameters=dict(
                min_silence_duration_ms=int(self._cfg.get("silence_ms", 450) or 450),
                speech_pad_ms=160,
            ),
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
        return " ".join(parts).strip()


class UtteranceAssembler:
    """PCM stream → finished utterances via energy VAD (endpoint before execute)."""

    def __init__(self):
        cfg = _load_stt_cfg()
        self.speech_rms = float(cfg.get("speech_rms", 0.012))
        self.silence_rms = float(cfg.get("silence_rms", 0.006))
        self.silence_ms = int(cfg.get("silence_ms", 550))
        self.min_speech_ms = int(cfg.get("min_speech_ms", 320))
        self.max_speech_ms = int(cfg.get("max_speech_ms", 12000))
        self.pre_roll_ms = int(cfg.get("pre_roll_ms", 220))
        self.hangover_ms = int(cfg.get("hangover_ms", 180))

        self._buf = np.zeros(0, dtype=np.float32)
        self._pre = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._muted = False

    def set_muted(self, muted: bool):
        self._muted = bool(muted)
        if self._muted:
            self.reset()

    def reset(self):
        self._buf = np.zeros(0, dtype=np.float32)
        self._pre = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._speech_started = 0.0
        self._last_voice = 0.0

    def push(self, pcm_f32: np.ndarray):
        if self._muted or pcm_f32 is None or len(pcm_f32) == 0:
            return None

        rms = float(np.sqrt(np.mean(np.square(pcm_f32)))) if len(pcm_f32) else 0.0
        now = time.time()
        pre_samples = int(SAMPLE_RATE * self.pre_roll_ms / 1000)

        if not self._in_speech:
            self._pre = np.concatenate([self._pre, pcm_f32])[-pre_samples:]
            if rms >= self.speech_rms:
                self._in_speech = True
                self._speech_started = now
                self._last_voice = now
                self._buf = np.concatenate([self._pre, pcm_f32])
                self._pre = np.zeros(0, dtype=np.float32)
            return None

        self._buf = np.concatenate([self._buf, pcm_f32])
        if rms >= self.silence_rms:
            self._last_voice = now

        elapsed_ms = (now - self._speech_started) * 1000
        silent_ms = (now - self._last_voice) * 1000

        end = False
        if silent_ms >= (self.silence_ms + self.hangover_ms) and elapsed_ms >= self.min_speech_ms:
            end = True
        elif elapsed_ms >= self.max_speech_ms:
            end = True

        if not end:
            return None

        clip = self._buf.copy()
        self.reset()
        if len(clip) < SAMPLE_RATE * (self.min_speech_ms / 1000):
            return None
        return clip

    def level(self, pcm_f32: np.ndarray) -> float:
        if pcm_f32 is None or len(pcm_f32) == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(pcm_f32))))
        return max(0.0, min(1.0, rms / 0.08))


_engine = None
_engine_lock = threading.Lock()


def get_engine() -> WhisperEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = WhisperEngine()
        return _engine
