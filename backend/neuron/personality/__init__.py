"""Personality engine — format replies, modes, emotion, conversation memory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from neuron.personality import buffer, humor, styles, voice
from neuron.personality.emotion import Emotion, detect_emotion
from neuron.personality.modes import ModeSpec, get_mode, normalize_mode

_STATE: dict[str, Any] = {"mode": None}


def _cfg() -> dict[str, Any]:
    try:
        root = Path(__file__).resolve().parents[2]
        return json.loads((root / "config.json").read_text(encoding="utf-8")).get("assistant") or {}
    except Exception:
        return {}


def enabled() -> bool:
    return bool(_cfg().get("personality_engine", True))


def current_mode_id() -> str:
    if _STATE.get("mode"):
        return normalize_mode(str(_STATE["mode"]))
    return normalize_mode(str(_cfg().get("mode") or "jarvis"))


def set_mode(mode: str) -> ModeSpec:
    mid = normalize_mode(mode)
    _STATE["mode"] = mid
    # Persist soft preference into runtime only; config write optional
    return get_mode(mid)


def get_mode_spec() -> ModeSpec:
    return get_mode(current_mode_id())


def assistant_name() -> str:
    return str(_cfg().get("name") or "NEURON")


def humor_enabled() -> bool:
    return bool(_cfg().get("humor", True))


def emotion_aware() -> bool:
    return bool(_cfg().get("emotion_aware", True))


_MODE_CMD = re.compile(
    r"\b(?:switch to|use|set|enable)\s+"
    r"(professional|friendly|jarvis|iron\s*man(?:\s+jarvis)?|formal|casual)\s*"
    r"(?:mode)?\b",
    re.I,
)


def maybe_handle_mode_command(text: str) -> tuple[str, bool, dict] | None:
    """Voice: 'switch to professional mode'."""
    m = _MODE_CMD.search(text or "")
    if not m:
        return None
    raw = m.group(1).lower().replace("iron man jarvis", "jarvis").replace("iron man", "jarvis")
    if "formal" in raw:
        raw = "professional"
    if "casual" in raw:
        raw = "friendly"
    spec = set_mode(raw)
    say = format_reply(
        f"{spec.label} mode enabled.",
        user=text,
        acted=True,
        path="personality",
    )
    return say, True, {"path": "personality", "mode": spec.id, "voice_hints": voice.voice_hints(spec, detect_emotion(text))}


def format_reply(
    say: str | None,
    *,
    user: str = "",
    acted: bool = True,
    path: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    if not enabled():
        return say or ""
    text = (say or "").strip()
    if not text or text.startswith("__"):
        return text

    mode = get_mode_spec()
    emo = detect_emotion(user) if emotion_aware() else Emotion("neutral", 0.0, [])
    text = styles.apply_speaking_style(text, mode, emo, name=assistant_name())
    if humor_enabled():
        text = humor.maybe_quip(text, mode, acted=acted, path=path, seed=user[:80])
    buffer.remember_turn(user, text, mode=mode.id, emotion=emo.label, path=path)
    if meta is not None:
        meta["personality"] = {
            "mode": mode.id,
            "emotion": emo.to_dict(),
            "voice_hints": voice.voice_hints(mode, emo),
            "speaking_style": mode.speaking_style,
        }
    return text


def status() -> dict[str, Any]:
    mode = get_mode_spec()
    return {
        "enabled": enabled(),
        "mode": mode.id,
        "label": mode.label,
        "speaking_style": mode.speaking_style,
        "voice_style": mode.voice_style,
        "humor": mode.humor,
        "humor_enabled": humor_enabled(),
        "emotion_aware": emotion_aware(),
        "name": assistant_name(),
        "conversation": buffer.recent(4),
        "prompt_blurb": mode.system_blurb,
    }


def system_prompt_addon() -> str:
    """Optional blurb for LLM system prompts."""
    mode = get_mode_spec()
    conv = buffer.for_prompt(3)
    parts = [f"PERSONALITY MODE ({mode.label}): {mode.system_blurb}"]
    if conv:
        parts.append(conv)
    return "\n".join(parts)


def tool_personality_status(args: dict | None = None) -> Any:
    from neuron.windows.result import ok
    st = status()
    return ok(f"Mode: {st['label']} ({st['mode']})", state=st, method="personality")


def tool_personality_set(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    mode = str(args.get("mode") or args.get("name") or "").strip()
    if not mode:
        return fail("Need mode: professional | friendly | jarvis")
    spec = set_mode(mode)
    return ok(
        format_reply(f"{spec.label} mode enabled.", user=f"set {mode}", acted=True, path="personality"),
        state=status(),
        method="personality",
    )


def tool_personality_detect(args: dict | None = None) -> Any:
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("text") or args.get("utterance") or "").strip()
    if not text:
        return fail("Need text.")
    emo = detect_emotion(text)
    hints = voice.voice_hints(get_mode_spec(), emo)
    return ok(f"Emotion: {emo.label} ({emo.score})", state={"emotion": emo.to_dict(), "voice_hints": hints})
