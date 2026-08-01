"""Detect production / release intents."""

from __future__ import annotations

import re
from typing import Any

from neuron.production.types import ProdCapability

_SINGLE_FAST = re.compile(
    r"^(mute|unmute|volume\s*up|volume\s*down|undo|redo|pause|play|"
    r"open\s+\w+|close\s+\w+|stop|cancel|confirm|yes)$",
    re.I,
)

_PR = re.compile(
    r"("
    r"production readiness|release audit|run diagnostics|"
    r"configuration wizard|config wizard|install neuron|"
    r"check for updates|production status|prepare for (public )?release|"
    r"apply (safe|balanced|performance|developer) preset|"
    r"system diagnostics|readiness report"
    r")",
    re.I,
)


def looks_like_production(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _SINGLE_FAST.match(t):
        return False
    low = t.lower()
    if low.startswith("production ") or low in ("run diagnostics", "configuration wizard"):
        return True
    return bool(_PR.search(t))


def classify_prod_intent(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    low = t.lower()

    if low in ("production status", "production readiness") or "readiness report" in low:
        return {"capability": ProdCapability.STATUS.value, "args": {}}

    if re.search(r"\b(release audit|audit (architecture|security|production))\b", low) or "prepare for public release" in low:
        return {"capability": ProdCapability.AUDIT.value, "args": {}}

    if re.search(r"\b(run diagnostics|system diagnostics)\b", low):
        return {"capability": ProdCapability.DIAGNOSTICS.value, "args": {}}

    if re.search(r"\b(configuration wizard|config wizard)\b", low):
        m = re.search(r"\b(safe|balanced|performance|developer)\b", low)
        return {"capability": ProdCapability.WIZARD.value, "args": {"preset": m.group(1) if m else "balanced"}}

    if re.search(r"\bapply (safe|balanced|performance|developer) preset\b", low):
        m = re.search(r"apply (safe|balanced|performance|developer) preset", low)
        return {"capability": ProdCapability.WIZARD.value, "args": {"preset": m.group(1)}}

    if re.search(r"\binstall neuron\b", low):
        return {"capability": ProdCapability.INSTALL.value, "args": {}}

    if re.search(r"\bcheck for updates\b", low):
        return {"capability": ProdCapability.UPDATE.value, "args": {}}

    return {"capability": ProdCapability.STATUS.value, "args": {}}
