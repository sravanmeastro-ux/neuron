"""Speech-to-text for N.E.U.R.O.N — free self-hosted OpenAI Whisper.

Uses https://github.com/openai/whisper locally (no paid API).
If PyTorch has no CUDA, falls back to faster-whisper with the same free
OpenAI model weights (GPU via ctranslate2).

Frontend streams 16 kHz mono Int16 PCM; energy VAD cuts utterances.
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
    """Map aliases to openai/whisper model ids."""
    n = (name or "turbo").strip().lower()
    aliases = {
        "whisper-1": "turbo",
        "openai": "turbo",
        "large-v3-turbo": "turbo",
        "large_v3_turbo": "turbo",
    }
    return aliases.get(n, n)


class WhisperEngine:
    """Free self-hosted OpenAI Whisper (github.com/openai/whisper)."""

    def __init__(self):
        self._model = None          # openai-whisper model
        self._fw_model = None       # faster-whisper fallback
        self._lock = threading.Lock()
        self._cfg = _load_stt_cfg()
        self._ready = False
        self._err = None
        self._backend = None        # "openai-whisper" | "faster-whisper"
        self._device = "cpu"

    def is_enabled(self) -> bool:
        return bool(self._cfg.get("enabled", True))

    def backend_name(self) -> str:
        return self._backend or "openai-whisper"

    def status_report(self) -> str:
        """Factual spoken answer for 'what speech recognition are you using?'."""
        self._ensure_model()
        if not self._ready:
            return (
                "Speech recognition isn't ready yet. "
                f"{self._err or 'Still loading OpenAI Whisper.'}"
            )
        model = _normalize_model_name(self._cfg.get("model", "turbo"))
        if self._backend == "openai-whisper":
            return (
                f"I'm using free self-hosted OpenAI Whisper, model {model}, "
                f"running locally on {self._device}. Not Windows Speech Recognition."
            )
        if self._backend == "faster-whisper":
            return (
                f"I'm using free OpenAI Whisper weights via faster-whisper, "
                f"model {model}, on {self._device}. Not Windows Speech Recognition."
            )
        return f"Speech engine: {self._backend} on {self._device}."

    def warmup(self) -> str:
        self._ensure_model()
        if not self._ready:
            raise RuntimeError(self._err or "Whisper failed to load")
        silence = np.zeros(SAMPLE_RATE // 4, dtype=np.float32)
        _ = self.transcribe(silence)
        model = _normalize_model_name(self._cfg.get("model", "turbo"))
        return f"Whisper ready ({self._backend} {model} on {self._device})."

    def _ensure_model(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self._cfg = _load_stt_cfg()
            want = (self._cfg.get("device") or "cuda").lower()
            # Prefer official openai-whisper when PyTorch can use the requested device.
            if self._try_openai_whisper(want):
                return
            print("[stt] openai-whisper unavailable or no GPU torch — trying faster-whisper", flush=True)
            if self._try_faster_whisper(want):
                return
            self._ready = False
            self._err = self._err or "Could not load local Whisper"

    def _try_openai_whisper(self, want_device: str) -> bool:
        try:
            import torch
            import whisper
        except Exception as exc:
            self._err = f"openai-whisper import failed: {exc}"
            print(f"[stt] {self._err}", flush=True)
            return False

        model_name = _normalize_model_name(self._cfg.get("model", "turbo"))
        force = (self._cfg.get("provider") or "").lower() in (
            "openai-whisper", "openai_whisper", "whisper",
        )
        if want_device.startswith("cuda") and not torch.cuda.is_available():
            if force:
                print(
                    "[stt] PyTorch has no CUDA — loading openai-whisper on CPU "
                    "(slower). Install CUDA torch for GPU.",
                    flush=True,
                )
                device = "cpu"
            else:
                print(
                    "[stt] PyTorch has no CUDA — skipping openai-whisper GPU path "
                    "(will use faster-whisper for GPU)",
                    flush=True,
                )
                return False
        else:
            device = "cuda" if want_device.startswith("cuda") and torch.cuda.is_available() else "cpu"
        try:
            print(f"[stt] loading openai/whisper '{model_name}' on {device}…", flush=True)
            self._model = whisper.load_model(model_name, device=device)
            self._device = device
            self._backend = "openai-whisper"
            self._ready = True
            self._err = None
            print(f"[stt] openai-whisper ready ({model_name} / {device})", flush=True)
            return True
        except Exception as exc:
            self._err = str(exc)
            print(f"[stt] openai-whisper load failed: {exc}", flush=True)
            self._model = None
            return False

    def _try_faster_whisper(self, want_device: str) -> bool:
        try:
            _add_cuda_dll_dirs()
            from faster_whisper import WhisperModel
        except Exception as exc:
            self._err = f"faster-whisper import failed: {exc}"
            print(f"[stt] {self._err}", flush=True)
            return False

        # Map openai model names → faster-whisper / HuggingFace ids
        raw = _normalize_model_name(self._cfg.get("model", "turbo"))
        fw_map = {
            "turbo": "large-v3-turbo",
            "large": "large-v3",
            "large-v3": "large-v3",
            "large-v2": "large-v2",
            "medium": "medium",
            "small": "small",
            "base": "base",
            "tiny": "tiny",
        }
        model_name = fw_map.get(raw, raw)
        device = "cuda" if want_device.startswith("cuda") else "cpu"
        compute = self._cfg.get("compute_type", "float16" if device == "cuda" else "int8")
        try:
            self._fw_model = WhisperModel(model_name, device=device, compute_type=compute)
            list(self._fw_model.transcribe(
                np.zeros(SAMPLE_RATE // 8, dtype=np.float32),
                language="en", vad_filter=False,
            ))
        except Exception as cuda_exc:
            print(f"[stt] faster-whisper {device} failed ({cuda_exc}); trying CPU", flush=True)
            try:
                self._fw_model = WhisperModel(model_name, device="cpu", compute_type="int8")
                device = "cpu"
            except Exception as exc:
                self._err = str(exc)
                print(f"[stt] faster-whisper load failed: {exc}", flush=True)
                return False

        self._device = device
        self._backend = "faster-whisper"
        self._ready = True
        self._err = None
        print(
            f"[stt] faster-whisper ready ({model_name} / {device}) "
            f"— free OpenAI Whisper weights",
            flush=True,
        )
        return True

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 mono 16 kHz clip. Returns cleaned text or ''."""
        self._ensure_model()
        if not self._ready or audio is None or len(audio) < SAMPLE_RATE * 0.2:
            return ""
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak < 1e-4:
            return ""
        if peak > 0:
            audio = audio / max(peak, 0.08)
            audio = np.clip(audio, -1.0, 1.0).astype(np.float32)

        with self._lock:
            if self._backend == "openai-whisper":
                text = self._transcribe_openai_whisper(audio)
            else:
                text = self._transcribe_faster(audio)
        return _clean_transcript(text)

    def _transcribe_openai_whisper(self, audio: np.ndarray) -> str:
        lang = self._cfg.get("language") or "en"
        fp16 = self._device == "cuda"
        result = self._model.transcribe(
            audio,
            language=None if lang == "auto" else lang,
            fp16=fp16,
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return (result.get("text") or "").strip()

    def _transcribe_faster(self, audio: np.ndarray) -> str:
        beam = int(self._cfg.get("beam_size", 1))
        segments, _info = self._fw_model.transcribe(
            audio,
            language=self._cfg.get("language", "en"),
            beam_size=beam,
            best_of=beam,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=160,
            ),
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        parts = [s.text.strip() for s in segments if s.text and s.text.strip()]
        return " ".join(parts).strip()


class UtteranceAssembler:
    """Turn a stream of PCM chunks into finished utterances via energy VAD."""

    def __init__(self):
        cfg = _load_stt_cfg()
        self.speech_rms = float(cfg.get("speech_rms", 0.012))
        self.silence_rms = float(cfg.get("silence_rms", 0.006))
        self.silence_ms = int(cfg.get("silence_ms", 450))
        self.min_speech_ms = int(cfg.get("min_speech_ms", 280))
        self.max_speech_ms = int(cfg.get("max_speech_ms", 12000))
        self.pre_roll_ms = int(cfg.get("pre_roll_ms", 200))

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
        """Feed float32 mono @ 16 kHz. Returns a finished utterance array or None."""
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
        if silent_ms >= self.silence_ms and elapsed_ms >= self.min_speech_ms:
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
