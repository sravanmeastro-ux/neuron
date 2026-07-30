"""Local wake-word gate — openWakeWord if installed, else transcript regex.

Everything stays on-device / free. No cloud wake APIs.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from neuron.speech.endpoint import strip_wake_prefix

_WAKE_RE = re.compile(
    r"\b(hey |hi |hello |ok |okay )?(neuron|jarvis|assistant)\b",
    re.I,
)

_oww_model = None
_oww_lock = threading.Lock()
_oww_err: str | None = None


def _voice_cfg() -> dict:
    try:
        import json
        from pathlib import Path
        return json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        ).get("voice", {}) or {}
    except Exception:
        return {}


def openwakeword_available() -> bool:
    try:
        import openwakeword  # noqa: F401
        return True
    except Exception:
        return False


def _ensure_oww():
    global _oww_model, _oww_err
    if _oww_model is not None or _oww_err:
        return _oww_model
    with _oww_lock:
        if _oww_model is not None or _oww_err:
            return _oww_model
        try:
            from openwakeword.model import Model
            # Built-in free models; map Neuron wake to hey_jarvis / hey_mycroft aliases
            models = _voice_cfg().get("openwakeword_models") or ["hey_jarvis"]
            if isinstance(models, str):
                models = [models]
            _oww_model = Model(wakeword_models=list(models), inference_framework="onnx")
            print(f"[wake] openWakeWord ready ({models})", flush=True)
        except Exception as exc:
            _oww_err = str(exc)
            print(f"[wake] openWakeWord unavailable: {exc}", flush=True)
            _oww_model = None
        return _oww_model


def score_pcm(pcm_f32, sample_rate: int = 16000) -> dict[str, float]:
    """Run openWakeWord on float32 mono PCM. Returns {model: score}."""
    model = _ensure_oww()
    if model is None or pcm_f32 is None:
        return {}
    try:
        import numpy as np
        audio = np.asarray(pcm_f32, dtype=np.float32)
        # openWakeWord expects int16
        pcm_i16 = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        # Feed in ~80ms frames
        frame = int(sample_rate * 0.08)
        scores: dict[str, float] = {}
        for i in range(0, max(0, len(pcm_i16) - frame), frame):
            chunk = pcm_i16[i : i + frame]
            pred = model.predict(chunk)
            if isinstance(pred, dict):
                for k, v in pred.items():
                    scores[k] = max(float(scores.get(k, 0)), float(v))
        return scores
    except Exception as exc:
        print(f"[wake] predict failed: {exc}", flush=True)
        return {}


def pcm_triggered_wake(pcm_f32, threshold: float | None = None) -> bool:
    thr = float(threshold if threshold is not None else _voice_cfg().get("openwakeword_threshold", 0.5))
    scores = score_pcm(pcm_f32)
    return any(v >= thr for v in scores.values())


def transcript_has_wake(text: str) -> bool:
    return bool(_WAKE_RE.search(text or ""))


def process_utterance(text: str, *, wake_required: bool, conversation_armed: bool) -> dict[str, Any]:
    """Decide if utterance should execute; strip wake prefix.

    Returns {allow, text, wake_only, armed_by_wake}.
    """
    raw = (text or "").strip()
    if not raw:
        return {"allow": False, "text": "", "wake_only": False, "armed_by_wake": False}

    # Safety / mode phrases always allowed
    if re.search(
        r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron|"
        r"hands free|wake word|conversation mode)\b",
        raw,
        re.I,
    ):
        return {"allow": True, "text": raw, "wake_only": False, "armed_by_wake": False}

    has_wake = transcript_has_wake(raw)
    command = strip_wake_prefix(raw)

    # Wake-only utterance: "Neuron." → arm conversation, don't execute empty
    if has_wake and not command:
        return {"allow": False, "text": "", "wake_only": True, "armed_by_wake": True}

    if not wake_required or conversation_armed:
        return {
            "allow": True,
            "text": command or raw,
            "wake_only": False,
            "armed_by_wake": has_wake,
        }

    # Wake required and not in conversation — need wake in this utterance
    if has_wake and command:
        return {"allow": True, "text": command, "wake_only": False, "armed_by_wake": True}

    return {"allow": False, "text": raw, "wake_only": False, "armed_by_wake": False}
