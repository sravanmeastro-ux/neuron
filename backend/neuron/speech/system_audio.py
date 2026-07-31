"""Detect loud system playback (YouTube, etc.) to gate mic STT.

Uses Windows default render device peak via pycaw when available.
No paid services. Fails open (assumes quiet) if metering is unavailable.
"""

from __future__ import annotations

import threading
import time
from typing import Any


_lock = threading.Lock()
_meter = None
_meter_err: str | None = None
_last_peak = 0.0
_last_poll = 0.0
_loud_since = 0.0
_quiet_since = 0.0


def _voice_cfg() -> dict[str, Any]:
    try:
        import json
        from pathlib import Path
        return json.loads(
            (Path(__file__).resolve().parent.parent.parent / "config.json").read_text(encoding="utf-8")
        ).get("voice", {}) or {}
    except Exception:
        return {}


def _ensure_meter():
    """Bind IAudioMeterInformation on the default render device."""
    global _meter, _meter_err
    if _meter is not None or _meter_err:
        return _meter
    with _lock:
        if _meter is not None or _meter_err:
            return _meter
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

            device = AudioUtilities.GetSpeakers()
            if device is None:
                _meter_err = "no default speakers"
                return None

            imm = getattr(device, "_dev", None)
            if imm is None or not hasattr(imm, "Activate"):
                _meter_err = "AudioDevice has no IMMDevice._dev"
                print(f"[system_audio] meter unavailable ({_meter_err}) — media gate soft-disabled", flush=True)
                return None

            iface = imm.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
            _meter = cast(iface, POINTER(IAudioMeterInformation))
            print("[system_audio] pycaw peak meter ready", flush=True)
            return _meter
        except Exception as exc:
            _meter_err = str(exc)
            print(f"[system_audio] meter unavailable ({exc}) — media gate soft-disabled", flush=True)
            return None


def render_peak(force: bool = False) -> float:
    """Peak meter 0.0–1.0 for the default playback device. Cached ~80ms."""
    global _last_peak, _last_poll
    now = time.time()
    if not force and (now - _last_poll) < 0.08:
        return _last_peak
    _last_poll = now
    meter = _ensure_meter()
    if meter is None:
        _last_peak = 0.0
        return 0.0
    try:
        peak = float(meter.GetPeakValue())
        _last_peak = max(0.0, min(1.0, peak))
        return _last_peak
    except Exception:
        _last_peak = 0.0
        return 0.0


def media_is_loud(*, cfg: dict | None = None) -> bool:
    """
    True when system playback has been above threshold long enough.

    Hysteresis avoids flicker when video dialogue pauses briefly.
    """
    global _loud_since, _quiet_since
    vcfg = cfg if cfg is not None else _voice_cfg()
    if not vcfg.get("media_gate_enabled", True):
        return False

    thr = float(vcfg.get("media_peak_threshold", 0.12) or 0.12)
    hold_ms = float(vcfg.get("media_loud_hold_ms", 400) or 400)
    release_ms = float(vcfg.get("media_quiet_release_ms", 1200) or 1200)
    peak = render_peak()
    now = time.time()

    if peak >= thr:
        if _loud_since <= 0:
            _loud_since = now
        _quiet_since = 0.0
        return (now - _loud_since) * 1000.0 >= hold_ms

    if _loud_since > 0:
        if _quiet_since <= 0:
            _quiet_since = now
        if (now - _quiet_since) * 1000.0 >= release_ms:
            _loud_since = 0.0
            _quiet_since = 0.0
            return False
        return True

    return False


def media_gate_status() -> dict[str, Any]:
    vcfg = _voice_cfg()
    return {
        "enabled": bool(vcfg.get("media_gate_enabled", True)),
        "peak": round(render_peak(force=True), 4),
        "loud": media_is_loud(cfg=vcfg),
        "threshold": float(vcfg.get("media_peak_threshold", 0.12) or 0.12),
        "meter": "pycaw" if _meter is not None else ("error" if _meter_err else "uninitialized"),
        "error": _meter_err,
    }


def reset_for_tests() -> None:
    global _meter, _meter_err, _last_peak, _last_poll, _loud_since, _quiet_since
    _meter = None
    _meter_err = None
    _last_peak = 0.0
    _last_poll = 0.0
    _loud_since = 0.0
    _quiet_since = 0.0
