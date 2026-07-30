"""Voice addressing mode — wake word optional; conversation mode for multi-turn.

Default: hands-free. User does NOT need to say "Neuron".
Optional: wake_word_required=true (+ openWakeWord) against ambient speech.
Conversation mode: after wake / command, stay armed without wake for a timeout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_WAKE_RE = re.compile(
    r"\b(hey |hi |hello )?(neuron|jarvis|assistant)\b",
    re.I,
)


def _voice_cfg() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("voice", {}) or {}
    except Exception:
        return {}


def wake_word_required() -> bool:
    return bool(_voice_cfg().get("wake_word_required", False))


def has_wake_word(text: str) -> bool:
    return bool(_WAKE_RE.search(text or ""))


def set_wake_word_required(required: bool) -> str:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    voice = cfg.setdefault("voice", {})
    voice["wake_word_required"] = bool(required)
    voice["hands_free"] = not bool(required)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    try:
        import memory
        memory.remember(
            "wake word",
            "required" if required else "not required — hands-free; just give commands",
        )
        memory.remember(
            "pc access",
            "full desktop control granted; act on plain speech without waiting to be named",
        )
    except Exception:
        pass
    if required:
        return (
            "Okay — I'll only act when you say my name first "
            "(Neuron / Jarvis). Say 'hands free mode' or 'conversation mode' to relax that."
        )
    return (
        "Hands-free on. Don't say Neuron — just give the command. "
        "I already have access to your PC."
    )


def set_conversation_mode(on: bool) -> str:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    voice = cfg.setdefault("voice", {})
    voice["conversation_mode"] = bool(on)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    try:
        from neuron.speech.session import get_session
        return get_session().set_conversation_mode(on)
    except Exception:
        return "Conversation mode on." if on else "Conversation mode off."


def allow_transcript(text: str) -> bool:
    """True if this utterance should run through the brain.

    Uses Phase 6 wake + conversation session when available.
    """
    t = (text or "").strip()
    if not t:
        return False
    if re.search(
        r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron|"
        r"hands free|wake word|conversation mode|end conversation)\b",
        t,
        re.I,
    ):
        return True

    try:
        from neuron.speech.session import get_session
        from neuron.speech import wake as wake_mod
        session = get_session()
        decision = wake_mod.process_utterance(
            t,
            wake_required=wake_word_required(),
            conversation_armed=session.is_armed() or session.conversation_mode,
        )
        if decision.get("wake_only"):
            session.on_wake()
            return False
        return bool(decision.get("allow"))
    except Exception:
        if not wake_word_required():
            return True
        return has_wake_word(t)


def bootstrap_hands_free() -> None:
    try:
        import memory
        if not wake_word_required():
            memory.remember(
                "wake word",
                "not required — hands-free; just give commands",
            )
            memory.remember(
                "pc access",
                "full desktop control granted; act on plain speech without waiting to be named",
            )
            memory.remember(
                "how to address me",
                "optional — user may say Neuron but does not need to",
            )
    except Exception:
        pass


def status() -> str:
    try:
        from neuron.speech.session import get_session
        s = get_session().status()
        bits = []
        if wake_word_required():
            bits.append("Wake word ON")
        else:
            bits.append("Hands-free")
        if s.get("conversation_mode"):
            bits.append("conversation mode")
        elif s.get("armed"):
            bits.append("temporarily armed")
        return " — ".join(bits) + "."
    except Exception:
        if wake_word_required():
            return "Wake word ON — say Neuron before commands."
        return "Hands-free — no need to say Neuron. Just command me."
