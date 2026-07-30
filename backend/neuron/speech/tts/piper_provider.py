"""Piper neural TTS provider (local/free)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from neuron.speech.tts.base import SpeakResult, TTSProvider


def _cfg() -> dict:
    try:
        cfg_path = Path(__file__).resolve().parent.parent.parent.parent / "config.json"
        return json.loads(cfg_path.read_text(encoding="utf-8")).get("tts", {}) or {}
    except Exception:
        return {}


class PiperProvider(TTSProvider):
    name = "piper"

    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def available(self) -> bool:
        cfg = _cfg()
        if not cfg.get("enabled", True):
            return False
        piper = cfg.get("piper_path") or shutil.which("piper") or ""
        model = cfg.get("model_path") or ""
        return bool(piper and model and Path(piper).exists() and Path(model).exists())

    def _paths(self) -> tuple[str, str]:
        cfg = _cfg()
        piper = cfg.get("piper_path") or shutil.which("piper") or ""
        model = cfg.get("model_path") or ""
        return piper, model

    def synthesize(self, text: str, out_path: Path) -> SpeakResult:
        text = (text or "").strip()
        if not text:
            return SpeakResult(engine=self.name, text="", path=None)
        piper, model = self._paths()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cmd = [piper, "--model", model, "--output_file", str(out_path)]
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert self._proc.stdin is not None
            self._proc.stdin.write(text.encode("utf-8"))
            self._proc.stdin.close()
            self._proc.wait(timeout=60)
            code = self._proc.returncode
            self._proc = None
            if code != 0 or not out_path.exists():
                return SpeakResult(
                    engine=self.name,
                    text=text,
                    error=f"piper exit {code}",
                )
            return SpeakResult(
                engine=self.name,
                text=text,
                path=str(out_path),
                audio_url=f"/tts_out/{out_path.name}",
            )
        except Exception as exc:
            self._proc = None
            return SpeakResult(engine=self.name, text=text, error=str(exc))

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
