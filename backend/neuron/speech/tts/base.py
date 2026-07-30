"""TTS provider interface — swap engines without changing callers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass
class SpeakResult:
    engine: str
    text: str
    path: str | None = None
    audio_url: str | None = None
    interrupted: bool = False
    chunks: int = 0
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "text": self.text,
            "path": self.path,
            "audio_url": self.audio_url,
            "interrupted": self.interrupted,
            "chunks": self.chunks,
            "error": self.error,
            **self.meta,
        }


class TTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def synthesize(self, text: str, out_path: Path) -> SpeakResult:
        """Write audio for `text` to out_path (wav preferred)."""

    def synthesize_stream(self, text: str, out_dir: Path) -> Iterator[SpeakResult]:
        """Optional streaming: yield per-chunk results. Default = one shot."""
        out = out_dir / "last.wav"
        yield self.synthesize(text, out)

    def stop(self) -> None:
        """Provider-level stop (optional)."""
        return None
