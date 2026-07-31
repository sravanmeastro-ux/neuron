"""Media bleed / speaker-loopback gate tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_bleed_phrases_rejected():
    from neuron.speech.endpoint import (
        is_complete_command,
        is_short_safe_command,
        reject_media_bleed,
    )

    assert not is_complete_command("you've built this program full screen the video").accept
    assert not is_complete_command("thanks for watching").accept
    assert not is_complete_command("(Thank you)").accept
    assert not is_complete_command("Thank you").accept
    assert is_complete_command("open chrome").accept
    assert is_complete_command("Neuron open chrome").accept
    assert is_complete_command("scroll down").accept
    assert is_short_safe_command("scroll down")
    assert is_short_safe_command("cancel")

    r = reject_media_bleed("the hero walked into the dark room slowly", media_loud=True)
    assert r is not None and not r.accept
    assert reject_media_bleed("open chrome", media_loud=True) is None
    assert reject_media_bleed("open chrome", media_loud=False) is None
    print("OK bleed phrase filters")


def test_pipeline_allows_scroll_when_loud():
    from unittest import mock
    from neuron.speech.pipeline import VoicePipeline
    from neuron.speech.session import VoiceSession
    import numpy as np

    sess = VoiceSession()
    pipe = VoicePipeline(session=sess)

    with mock.patch.object(pipe, "_apply_media_gate", return_value=True), mock.patch.object(
        pipe.assembler, "push", return_value=np.zeros(16000, dtype=np.float32)
    ), mock.patch.object(
        pipe.engine, "is_enabled", return_value=True
    ), mock.patch.object(
        pipe.engine, "transcribe", return_value="scroll down"
    ), mock.patch.object(
        pipe, "_cfg", return_value={
            "media_gate_enabled": True,
            "media_require_wake": True,
            "partial_interval_seconds": 99,
            "wake_required": False,
        }
    ):
        events = pipe.push_pcm(np.zeros(1600, dtype=np.float32))
    kinds = [e.kind for e in events]
    assert "final" in kinds or "command" in kinds, kinds
    assert "rejected" not in kinds
    print("OK scroll down accepted while media loud", kinds)


def test_media_gate_status():
    from neuron.speech import system_audio as sa

    sa.reset_for_tests()
    st = sa.media_gate_status()
    assert "peak" in st and "loud" in st
    print("OK media_gate_status", st.get("meter"), "peak=", st.get("peak"))


def test_pipeline_forces_wake_when_loud(monkeypatch=None):
    from unittest import mock
    from neuron.speech.pipeline import VoicePipeline
    from neuron.speech.session import VoiceSession
    import numpy as np

    sess = VoiceSession()
    pipe = VoicePipeline(session=sess)

    # Stub STT/assembler to emit a final dialogue clip
    with mock.patch.object(pipe, "_apply_media_gate", return_value=True), mock.patch.object(
        pipe.assembler, "push", return_value=np.zeros(16000, dtype=np.float32)
    ), mock.patch.object(
        pipe.engine, "is_enabled", return_value=True
    ), mock.patch.object(
        pipe.engine, "transcribe", return_value="the hero walked into the dark room slowly"
    ), mock.patch.object(
        pipe, "_cfg", return_value={
            "media_gate_enabled": True,
            "media_require_wake": True,
            "partial_interval_seconds": 99,
        }
    ):
        events = pipe.push_pcm(np.zeros(1600, dtype=np.float32))
    kinds = [e.kind for e in events]
    assert "rejected" in kinds
    rej = next(e for e in events if e.kind == "rejected")
    assert rej.meta and rej.meta.get("reason") in (
        "media_bleed_long", "media_bleed_phrase", "media_wake_gate", "wake_gate"
    )
    print("OK pipeline rejects loud media dialogue", rej.meta)


if __name__ == "__main__":
    test_bleed_phrases_rejected()
    test_media_gate_status()
    test_pipeline_forces_wake_when_loud()
    test_pipeline_allows_scroll_when_loud()
    print("\nALL media-gate tests passed")
