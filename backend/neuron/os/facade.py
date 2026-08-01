"""Stable NEURON OS facade APIs for other modules / tools."""

from __future__ import annotations

from typing import Any

from neuron.os import kernel
from neuron.os.types import CapabilityId, OsResult


def launch(name: str) -> OsResult:
    return kernel.dispatch(CapabilityId.LAUNCHER.value, {"name": name})


def windows(op: str = "list", **kwargs: Any) -> OsResult:
    return kernel.dispatch(CapabilityId.WINDOW_MANAGER.value, {"op": op, **kwargs})


def monitor() -> OsResult:
    return kernel.dispatch(CapabilityId.SYSTEM_MONITOR.value, {})


def notify(message: str, *, level: str = "info") -> OsResult:
    return kernel.dispatch(CapabilityId.NOTIFICATIONS.value, {"message": message, "level": level})


def automate(op: str = "list", **kwargs: Any) -> OsResult:
    return kernel.dispatch(CapabilityId.AUTOMATION_HUB.value, {"op": op, **kwargs})


def voice_status() -> OsResult:
    return kernel.dispatch(CapabilityId.VOICE_FIRST.value, {})


def context(text: str = "") -> OsResult:
    return kernel.dispatch(CapabilityId.CONTEXT.value, {"text": text})


def computer_use(goal: str, *, confirmed: bool = False) -> OsResult:
    return kernel.dispatch(CapabilityId.COMPUTER_USE.value, {"text": goal, "confirmed": confirmed})


def plan(goal: str, *, confirmed: bool = False) -> OsResult:
    return kernel.dispatch(CapabilityId.AI_PLANNING.value, {"text": goal, "confirmed": confirmed})


def vision(request: str) -> OsResult:
    return kernel.dispatch(CapabilityId.VISION.value, {"request": request})


def memory(op: str = "query", text: str = "") -> OsResult:
    return kernel.dispatch(CapabilityId.MEMORY.value, {"op": op, "text": text})


def learning() -> OsResult:
    return kernel.dispatch(CapabilityId.LEARNING.value, {})


def plugins() -> OsResult:
    return kernel.dispatch(CapabilityId.PLUGINS.value, {})


def status() -> dict[str, Any]:
    kernel.boot()
    from neuron.os import capabilities as caps
    rep = kernel.status()
    return {
        **rep.to_dict(),
        "capabilities_detail": caps.list_capabilities(),
    }
