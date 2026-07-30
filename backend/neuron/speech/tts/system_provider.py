"""Windows SAPI / pyttsx3 TTS provider — free local fallback."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from neuron.speech.tts.base import SpeakResult, TTSProvider


def _cfg() -> dict:
    try:
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "config.json"
        return json.loads(cfg_path.read_text(encoding="utf-8")).get("tts", {}) or {}
    except Exception:
        return {}


class SystemProvider(TTSProvider):
    """pyttsx3 (SAPI5 on Windows) — free, interruptible, no cloud."""

    name = "system"

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def available(self) -> bool:
        cfg = _cfg()
        if cfg.get("system_tts_enabled") is False:
            return False
        try:
            import pyttsx3  # noqa: F401
            return True
        except Exception:
            return False

    def _get_engine(self):
        import pyttsx3
        if self._engine is None:
            self._engine = pyttsx3.init()
            rate = int(_cfg().get("rate", 185) or 185)
            try:
                self._engine.setProperty("rate", rate)
            except Exception:
                pass
            # Prefer a natural English voice if present
            prefer = (_cfg().get("voice_name") or "").lower()
            try:
                for v in self._engine.getProperty("voices") or []:
                    name = (getattr(v, "name", "") or "").lower()
                    vid = (getattr(v, "id", "") or "").lower()
                    if prefer and (prefer in name or prefer in vid):
                        self._engine.setProperty("voice", v.id)
                        break
                    if any(x in name for x in ("zira", "jenny", "aria", "natural", "english")):
                        self._engine.setProperty("voice", v.id)
                        break
            except Exception:
                pass
        return self._engine

    def synthesize(self, text: str, out_path: Path) -> SpeakResult:
        text = (text or "").strip()
        if not text:
            return SpeakResult(engine=self.name, text="")
        self._stop.clear()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                eng = self._get_engine()
                # pyttsx3 can save to file on many backends
                try:
                    eng.save_to_file(text, str(out_path))
                    eng.runAndWait()
                except Exception:
                    # Fallback: speak then we can't file — mark browser
                    return SpeakResult(
                        engine=self.name,
                        text=text,
                        error="save_to_file unsupported",
                        meta={"play_live": True},
                    )
            if self._stop.is_set():
                return SpeakResult(engine=self.name, text=text, interrupted=True)
            if out_path.exists() and out_path.stat().st_size > 44:
                return SpeakResult(
                    engine=self.name,
                    text=text,
                    path=str(out_path),
                    audio_url=f"/tts_out/{out_path.name}",
                )
            return SpeakResult(engine=self.name, text=text, error="no audio file")
        except Exception as exc:
            return SpeakResult(engine=self.name, text=text, error=str(exc))

    def stop(self) -> None:
        self._stop.set()
        try:
            with self._lock:
                if self._engine is not None:
                    self._engine.stop()
        except Exception:
            pass
