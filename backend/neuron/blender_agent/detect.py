"""Detect Blender expert intents — never steal Category A."""

from __future__ import annotations

import re
from typing import Any

from neuron.blender_agent.types import BlenderCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+(?!blender)\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_BLENDER = re.compile(
    r"\b("
    r"blender|soda can|cycles|eevee|geometry nodes?|procedural material|"
    r"rig(?:ging)?|animate|animation|topology|render|"
    r"create (a )?(cube|sphere|cylinder|mesh|object)|"
    r"import (model|mesh|fbx|obj|gltf)|export (model|fbx|obj|glb)|"
    r"lighting|three[- ]point|camera setup|physics|rigid body|"
    r"texture generation|asset management|blender assets"
    r")\b",
    re.I,
)


def looks_like_blender(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t) and "blender" not in t.lower():
        return False
    low = t.lower()
    if low.startswith("blender ") or low in ("open blender", "blender status"):
        return True
    return bool(_BLENDER.search(t))


def classify_blender_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if low in ("blender status", "blender agent") or "blender status" in low:
        return {"capability": BlenderCapability.STATUS.value, "args": {}}

    if re.search(r"\bopen blender\b", low):
        return {"capability": BlenderCapability.OPEN.value, "args": {}}

    if "soda can" in low or re.search(r"\brealistic soda\b", low):
        return {"capability": BlenderCapability.CREATE.value, "args": {"recipe": "soda_can"}}

    if re.search(r"\b(procedural material|generate (a )?material|material)\b", low):
        return {"capability": BlenderCapability.MATERIAL.value, "args": {"style": "procedural"}}

    if "geometry node" in low or "geo nodes" in low or "geonodes" in low:
        return {"capability": BlenderCapability.GEONODES.value, "args": {}}

    if "topology" in low:
        return {"capability": BlenderCapability.TOPOLOGY.value, "args": {}}

    if re.search(r"\brender\b", low):
        engine = "CYCLES" if "cycles" in low else ("EEVEE" if "eevee" in low else "CYCLES")
        return {"capability": BlenderCapability.RENDER.value, "args": {"engine": engine}}

    if re.search(r"\b(animate|animation)\b", low):
        return {"capability": BlenderCapability.ANIMATION.value, "args": {}}

    if re.search(r"\brig", low):
        return {"capability": BlenderCapability.RIGGING.value, "args": {}}

    if re.search(r"\b(lighting|three[- ]point|studio light)\b", low):
        return {"capability": BlenderCapability.LIGHTING.value, "args": {}}

    if re.search(r"\bcamera\b", low):
        return {"capability": BlenderCapability.CAMERA.value, "args": {}}

    if re.search(r"\bphysics|rigid body\b", low):
        return {"capability": BlenderCapability.PHYSICS.value, "args": {}}

    if re.search(r"\btexture\b", low):
        return {"capability": BlenderCapability.TEXTURE.value, "args": {}}

    if re.search(r"\b(asset management|list assets|blender assets)\b", low):
        return {"capability": BlenderCapability.ASSETS.value, "args": {}}

    if re.search(r"\bimport\b", low):
        m = re.search(r"(?:import)\s+(\S+)", t, re.I)
        return {"capability": BlenderCapability.IMPORT.value, "args": {"path": m.group(1) if m else ""}}

    if re.search(r"\bexport\b", low):
        fmt = "glb"
        if "fbx" in low:
            fmt = "fbx"
        elif "obj" in low:
            fmt = "obj"
        return {"capability": BlenderCapability.EXPORT.value, "args": {"format": fmt}}

    if re.search(r"\bcreate\b", low):
        kind = "cube"
        for k in ("sphere", "cylinder", "plane", "torus", "cone", "monkey", "cube"):
            if k in low:
                kind = k
                break
        return {"capability": BlenderCapability.CREATE.value, "args": {"kind": kind}}

    return {"capability": BlenderCapability.STATUS.value, "args": {}}
