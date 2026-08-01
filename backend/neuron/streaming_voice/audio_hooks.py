"""Audio preprocessing hooks — echo cancellation + noise suppression.

These are production-ready *hooks*: they apply lightweight DSP when enabled
and pass through when disabled / unavailable. Browser getUserMedia may also
apply echoCancellation/noiseSuppression; this layer covers native PCM paths.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from neuron.streaming_voice import config as cfg_mod


class AudioProcessor(Protocol):
    def process(self, pcm: np.ndarray, *, sample_rate: int = 16000) -> np.ndarray: ...


class PassThrough:
    def process(self, pcm: np.ndarray, *, sample_rate: int = 16000) -> np.ndarray:
        return pcm


class NoiseGateSuppressor:
    """Soft noise gate — attenuates below-floor energy (not a full RNNoise)."""

    def __init__(self, floor: float = 0.004, attenuate: float = 0.15):
        self.floor = float(floor)
        self.attenuate = float(attenuate)

    def process(self, pcm: np.ndarray, *, sample_rate: int = 16000) -> np.ndarray:
        if pcm is None or len(pcm) == 0:
            return pcm
        x = np.asarray(pcm, dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(x))) + 1e-12)
        if rms < self.floor:
            return x * self.attenuate
        return x


class EchoCancellerHook:
    """
    Adaptive echo attenuation while TTS is speaking.

    Full AEC needs a reference loopback; here we soft-gate mic energy while
    NEURON is speaking (pairs with barge-in at higher levels).
    """

    def __init__(self, speak_attenuate: float = 0.35):
        self.speak_attenuate = float(speak_attenuate)

    def process(self, pcm: np.ndarray, *, sample_rate: int = 16000) -> np.ndarray:
        if pcm is None or len(pcm) == 0:
            return pcm
        speaking = False
        try:
            from neuron.speech.tts import is_speaking
            speaking = bool(is_speaking())
        except Exception:
            try:
                from neuron.speech.session import get_session
                speaking = bool(getattr(get_session(), "speaking", False))
            except Exception:
                speaking = False
        x = np.asarray(pcm, dtype=np.float32)
        if speaking:
            return x * self.speak_attenuate
        return x


class AudioChain:
    """Ordered preprocess: noise → echo (configurable)."""

    def __init__(self):
        self.noise = NoiseGateSuppressor()
        self.echo = EchoCancellerHook()
        self.passthrough = PassThrough()

    def process(self, pcm: np.ndarray, *, sample_rate: int = 16000) -> np.ndarray:
        x = np.asarray(pcm, dtype=np.float32)
        if cfg_mod.noise_suppression_enabled():
            x = self.noise.process(x, sample_rate=sample_rate)
        if cfg_mod.echo_cancellation_enabled():
            x = self.echo.process(x, sample_rate=sample_rate)
        return x


_CHAIN: AudioChain | None = None


def get_audio_chain() -> AudioChain:
    global _CHAIN
    if _CHAIN is None:
        _CHAIN = AudioChain()
    return _CHAIN
