"""Benchmarks for Personality engine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    import neuron.personality.buffer as buf
    buf._PATH = Path(__file__).with_name("_personality_bench.json")
    buf._TURNS = []
    if buf._PATH.exists():
        buf._PATH.unlink()

    from neuron.personality import (
        detect_emotion,
        format_reply,
        maybe_handle_mode_command,
        set_mode,
        status,
        system_prompt_addon,
    )
    from neuron.personality.emotion import detect_emotion as de
    from neuron.personality.modes import get_mode
    from neuron.personality.voice import voice_hints

    # Modes
    for mid in ("professional", "friendly", "jarvis"):
        assert get_mode(mid).id == mid
    set_mode("jarvis")
    assert status()["mode"] == "jarvis"
    print("OK modes")

    # Emotion
    assert de("thanks so much").label == "grateful"
    assert de("do this ASAP right now").label == "urgent"
    assert de("this is broken again damn").label == "frustrated"
    print("OK emotion")

    # Speaking styles
    set_mode("professional")
    pro = format_reply("hey gonna open chrome", user="open chrome", acted=True, path="test")
    assert "gonna" not in pro.lower()
    print(f"OK professional {pro!r}")

    set_mode("friendly")
    fr = format_reply("Done.", user="thanks!", acted=True, path="test")
    assert "Done" in fr or "done" in fr.lower()
    print(f"OK friendly {fr!r}")

    set_mode("jarvis")
    j = format_reply("Opened Chrome.", user="open chrome urgently now", acted=True, path="test", meta={})
    assert "Opened" in j or "Right away" in j
    print(f"OK jarvis {j!r}")

    # Conversation memory
    recent = buf.recent(4)
    assert len(recent) >= 1
    assert buf.for_prompt(2)
    print(f"OK conversation turns={len(recent)}")

    # Voice hints
    hints = voice_hints(get_mode("jarvis"), de("hurry ASAP"))
    assert hints["rate"] >= 185
    assert hints["emotion"] == "urgent"
    print(f"OK voice_hints rate={hints['rate']}")

    # Mode command
    set_mode("jarvis")
    out = maybe_handle_mode_command("switch to professional mode")
    assert out and out[2].get("mode") == "professional"
    print("OK mode command")

    # System prompt addon
    addon = system_prompt_addon()
    assert "PERSONALITY MODE" in addon
    print("OK system_prompt_addon")

    # Tools
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    for name in ("personality_status", "personality_set", "personality_detect"):
        assert tool_registry.get(name), name
    print("OK tools")

    print("PASS personality_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
