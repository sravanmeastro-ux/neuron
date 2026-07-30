"""Phase 7 local TTS — modular providers, speak/stop/is_speaking, barge-in."""

from __future__ import annotations

import sys
import threading
import time
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _write_silence_wav(path: Path, seconds: float = 0.05, rate: int = 16000) -> None:
    n = int(rate * seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)


def test_api_exports():
    from neuron.speech.tts import SpeakResult, get_tts, is_speaking, speak, status, stop_speaking

    assert callable(speak) and callable(stop_speaking) and callable(is_speaking)
    assert callable(get_tts) and callable(status)
    assert SpeakResult
    print("OK exports", status())


def test_provider_priority_and_browser_fallback():
    from neuron.speech.tts.engine import TTSEngine
    from neuron.speech.tts.browser_provider import BrowserProvider

    eng = TTSEngine()
    # Force empty piper/system by mocking available
    for p in eng._providers:
        if p.name != "browser":
            p.available = lambda: False  # type: ignore
    pick = eng._pick()
    assert pick.name == "browser"
    result = eng.speak("Hello from NEURON.")
    assert result.engine == "browser"
    assert result.text.startswith("Hello")
    assert not is_speaking_safe(eng)
    print("OK browser fallback", result.to_dict())


def is_speaking_safe(eng) -> bool:
    return eng.is_speaking()


def test_fake_provider_speak_stop():
    from neuron.speech.tts.base import SpeakResult, TTSProvider
    from neuron.speech.tts.engine import TTSEngine
    import neuron.speech.tts.engine as eng_mod

    class SlowProvider(TTSProvider):
        name = "fake"

        def __init__(self):
            self.calls = 0
            self.stopped = False

        def available(self) -> bool:
            return True

        def synthesize(self, text, out_path: Path) -> SpeakResult:
            self.calls += 1
            for _ in range(20):
                if self.stopped:
                    break
                time.sleep(0.02)
            _write_silence_wav(Path(out_path), 0.05)
            return SpeakResult(
                engine=self.name,
                text=text,
                path=str(out_path),
                audio_url=f"/tts_out/{Path(out_path).name}",
            )

        def stop(self) -> None:
            self.stopped = True

    eng = TTSEngine()
    fake = SlowProvider()
    eng._providers = [fake]

    results: list = []

    def run():
        with mock.patch.object(
            eng_mod,
            "_split_chunks",
            return_value=["One sentence.", "Two sentence.", "Three sentence."],
        ):
            results.append(eng.speak("ignored text for chunking", streaming=True))

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.05)
    assert eng.is_speaking()
    stop = eng.stop_speaking()
    assert stop["speaking"] is False
    t.join(timeout=5)
    assert not eng.is_speaking()
    assert fake.stopped
    assert results and (results[0].interrupted or results[0].chunks < 3)
    print("OK interruptible speak", results[0].to_dict(), "calls", fake.calls)


def test_chunk_split():
    from neuron.speech.tts.engine import _split_chunks

    parts = _split_chunks(
        "Hello world. How are you? Fine; thanks.",
        max_chars=20,
    )
    assert len(parts) >= 2
    assert all(parts)
    print("OK chunks", parts)


def test_concat_wavs():
    from neuron.speech.tts.engine import OUT_DIR, _concat_wavs

    a = OUT_DIR / "_t_a.wav"
    b = OUT_DIR / "_t_b.wav"
    dest = OUT_DIR / "_t_merged.wav"
    _write_silence_wav(a, 0.05)
    _write_silence_wav(b, 0.05)
    assert _concat_wavs([str(a), str(b)], dest)
    with wave.open(str(dest), "rb") as w:
        assert w.getnframes() > 0
    print("OK concat wav")


def test_compat_wrapper():
    from neuron.speech import tts_piper

    with mock.patch("neuron.speech.tts.engine.speak") as m:
        from neuron.speech.tts.base import SpeakResult

        m.return_value = SpeakResult(engine="browser", text="hi", path=None)
        d = tts_piper.speak_to_file("hi")
        assert d["engine"] == "browser"
        assert m.called
    print("OK tts_piper compat")


def test_module_is_speaking_flag():
    from neuron.speech.tts import engine as eng_mod
    from neuron.speech.tts.base import SpeakResult, TTSProvider

    class Instant(TTSProvider):
        name = "instant"

        def available(self) -> bool:
            return True

        def synthesize(self, text, out_path: Path) -> SpeakResult:
            _write_silence_wav(Path(out_path), 0.02)
            return SpeakResult(engine=self.name, text=text, path=str(out_path))

    eng = eng_mod.TTSEngine()
    eng._providers = [Instant()]
    # Replace singleton briefly
    old = eng_mod._ENGINE
    eng_mod._ENGINE = eng
    try:
        r = eng_mod.speak("One. Two. Three.", streaming=False)
        assert r.engine == "instant"
        assert r.path
        assert eng_mod.is_speaking() is False
        eng_mod.stop_speaking()
        assert eng_mod.is_speaking() is False
    finally:
        eng_mod._ENGINE = old
    print("OK module speak/stop/is_speaking")


if __name__ == "__main__":
    test_api_exports()
    test_provider_priority_and_browser_fallback()
    test_fake_provider_speak_stop()
    test_chunk_split()
    test_concat_wavs()
    test_compat_wrapper()
    test_module_is_speaking_flag()
    print("\nPhase 7 TTS tests passed.")
