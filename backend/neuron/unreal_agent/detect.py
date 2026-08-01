"""Detect Unreal Engine expert intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.unreal_agent.types import UnrealCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+(?!unreal)\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_UE = re.compile(
    r"\b("
    r"unreal|ue5|ue4|uproject|blueprint|niagara|sequencer|lumen|"
    r"third[- ]person character|package (the )?game|optimize fps|"
    r"landscape|nanite|gameplay ability|crash dump|uat |"
    r"generate (a )?niagara|fire effect|cook content|"
    r"unreal (engine|editor)|c\+\+ (actor|character)|material instance"
    r")\b",
    re.I,
)


def looks_like_unreal(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t) and "unreal" not in t.lower():
        return False
    low = t.lower()
    if low.startswith("unreal ") or low in ("unreal status", "open unreal"):
        return True
    return bool(_UE.search(t))


def classify_unreal_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if "unreal status" in low or low == "unreal agent":
        return {"capability": UnrealCapability.STATUS.value, "args": {}}
    if re.search(r"\bopen unreal\b", low):
        return {"capability": UnrealCapability.OPEN.value, "args": {}}

    if re.search(r"\bthird[- ]person character\b", low) or re.search(r"\bcreate (a )?character\b", low):
        return {"capability": UnrealCapability.CHARACTER.value, "args": {"name": "TP_Character"}}

    if "niagara" in low or "fire effect" in low:
        return {"capability": UnrealCapability.NIAGARA.value, "args": {"name": "NS_Fire"}}

    if re.search(r"\boptimize fps\b", low) or re.search(r"\boptimization\b", low):
        return {"capability": UnrealCapability.OPTIMIZATION.value, "args": {}}

    if re.search(r"\bpackage (the )?game\b", low) or "packaging" in low or "cook content" in low:
        return {"capability": UnrealCapability.PACKAGING.value, "args": {}}

    if re.search(r"\b(build monitor|monitor build|compile (the )?project)\b", low) or (
        "build" in low and "unreal" in low
    ):
        return {"capability": UnrealCapability.BUILD.value, "args": {}}

    if "crash" in low or "assertion failed" in low or "fatal error" in low:
        return {"capability": UnrealCapability.CRASH.value, "args": {"text": t}}

    if "blueprint" in low:
        return {"capability": UnrealCapability.BLUEPRINT.value, "args": {"kind": "generic"}}

    if "c++" in low or "cpp" in low:
        return {"capability": UnrealCapability.CPP.value, "args": {"name": "NeuronActor"}}

    if "material" in low:
        return {"capability": UnrealCapability.MATERIAL.value, "args": {}}

    if "landscape" in low:
        return {"capability": UnrealCapability.LANDSCAPE.value, "args": {}}

    if "sequencer" in low or "cinematic" in low:
        return {"capability": UnrealCapability.SEQUENCER.value, "args": {}}

    if "animation" in low or "anim bp" in low:
        return {"capability": UnrealCapability.ANIMATION.value, "args": {}}

    if "lighting" in low or "lumen" in low:
        return {"capability": UnrealCapability.LIGHTING.value, "args": {}}

    if "project" in low and "unreal" in low:
        return {"capability": UnrealCapability.PROJECT.value, "args": {}}

    return {"capability": UnrealCapability.STATUS.value, "args": {}}
