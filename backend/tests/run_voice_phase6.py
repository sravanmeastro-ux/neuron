"""Phase 6 local voice tests — endpointing, wake gate, conversation session."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_reject_partials():
    from neuron.speech.endpoint import is_complete_command

    assert not is_complete_command("um").accept
    assert not is_complete_command("thank you").accept
    assert not is_complete_command("open the").accept  # incomplete trailing
    assert is_complete_command("open chrome").accept
    assert is_complete_command("Open YouTube and play some music").accept
    print("OK endpoint gate")


def test_strip_wake():
    from neuron.speech.endpoint import strip_wake_prefix

    assert strip_wake_prefix("Neuron.") == ""
    assert strip_wake_prefix("Neuron, open chrome").lower() == "open chrome"
    assert "youtube" in strip_wake_prefix("Hey Neuron open youtube").lower()
    print("OK strip wake")


def test_wake_then_command():
    from neuron.speech import wake as wake_mod
    from neuron.speech.session import VoiceSession

    session = VoiceSession()
    # Wake only
    d = wake_mod.process_utterance("Neuron.", wake_required=True, conversation_armed=False)
    assert d["wake_only"] and d["armed_by_wake"]
    session.on_wake()
    assert session.is_armed()
    # Command while armed (no wake needed)
    d2 = wake_mod.process_utterance(
        "Open YouTube and play some music",
        wake_required=True,
        conversation_armed=session.is_armed(),
    )
    assert d2["allow"]
    assert "youtube" in d2["text"].lower()
    print("OK wake then command", d2["text"])


def test_hands_free_no_wake():
    from neuron.speech import wake as wake_mod

    d = wake_mod.process_utterance("open notepad", wake_required=False, conversation_armed=False)
    assert d["allow"] and d["text"].lower().startswith("open")
    print("OK hands-free")


def test_conversation_mode():
    from neuron.speech.session import VoiceSession

    s = VoiceSession()
    msg = s.set_conversation_mode(True)
    assert s.conversation_mode
    assert "Conversation" in msg
    s.set_conversation_mode(False)
    assert not s.conversation_mode
    print("OK conversation mode")


def test_vad_endpoint_silence():
    import stt

    asm = stt.UtteranceAssembler()
    asm.silence_ms = 50
    asm.hangover_ms = 20
    asm.min_speech_ms = 50
    # Speech-like energy
    speech = np.random.randn(stt.SAMPLE_RATE // 10).astype(np.float32) * 0.05
    silence = np.zeros(stt.SAMPLE_RATE // 20, dtype=np.float32)
    out = None
    for _ in range(5):
        out = asm.push(speech)
    import time
    time.sleep(0.12)
    for _ in range(10):
        out = asm.push(silence)
        if out is not None:
            break
    assert out is not None and len(out) > 0
    print("OK VAD endpoint", len(out))


def test_pipeline_rejects_junk_without_brain():
    from neuron.speech.pipeline import VoicePipeline
    from neuron.speech.session import VoiceSession

    pipe = VoicePipeline(VoiceSession())
    with mock.patch.object(pipe.engine, "is_enabled", return_value=True), mock.patch.object(
        pipe.engine, "transcribe", return_value="um"
    ), mock.patch.object(pipe.assembler, "push", return_value=np.zeros(16000, dtype=np.float32)):
        events = pipe.push_pcm(np.zeros(1600, dtype=np.float32))
    kinds = [e.kind for e in events]
    assert "final" not in kinds
    assert "rejected" in kinds
    print("OK pipeline reject junk")


def test_voice_mode_allow():
    import voice_mode

    # Hands-free default should allow
    with mock.patch.object(voice_mode, "wake_word_required", return_value=False):
        assert voice_mode.allow_transcript("open chrome")
    print("OK voice_mode allow")


if __name__ == "__main__":
    test_reject_partials()
    test_strip_wake()
    test_wake_then_command()
    test_hands_free_no_wake()
    test_conversation_mode()
    test_vad_endpoint_silence()
    test_pipeline_rejects_junk_without_brain()
    test_voice_mode_allow()
    print("\n=== Phase 6 voice tests passed ===")
