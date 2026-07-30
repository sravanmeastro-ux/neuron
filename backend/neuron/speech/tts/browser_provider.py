"""Browser speechSynthesis provider — signals frontend to speak."""

from __future__ import annotations

from pathlib import Path

from neuron.speech.tts.base import SpeakResult, TTSProvider


class BrowserProvider(TTSProvider):
    name = "browser"

    def available(self) -> bool:
        return True

    def synthesize(self, text: str, out_path: Path) -> SpeakResult:
        # No server-side audio — frontend uses speechSynthesis
        return SpeakResult(
            engine=self.name,
            text=(text or "").strip(),
            meta={"client": "speechSynthesis"},
        )

    def stop(self) -> None:
        return None
