"""NEURON OS types — capabilities, results, session."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CapabilityId(str, Enum):
    LAUNCHER = "launcher"
    WINDOW_MANAGER = "window_manager"
    SYSTEM_MONITOR = "system_monitor"
    NOTIFICATIONS = "notifications"
    AUTOMATION_HUB = "automation_hub"
    VOICE_FIRST = "voice_first"
    CONTEXT = "context"
    COMPUTER_USE = "computer_use"
    AI_PLANNING = "ai_planning"
    VISION = "vision"
    MEMORY = "memory"
    LEARNING = "learning"
    PLUGINS = "plugins"


CAPABILITY_META: dict[str, dict[str, str]] = {
    CapabilityId.LAUNCHER.value: {
        "label": "Universal Launcher",
        "composes": "open_app / plugins / focus_app",
    },
    CapabilityId.WINDOW_MANAGER.value: {
        "label": "Window Manager",
        "composes": "get_windows / move_window / focus / minimize / maximize",
    },
    CapabilityId.SYSTEM_MONITOR.value: {
        "label": "System Monitor",
        "composes": "windows.state.snapshot / processes / monitors",
    },
    CapabilityId.NOTIFICATIONS.value: {
        "label": "Notification Manager",
        "composes": "speak / confirm prompts / settings notifications",
    },
    CapabilityId.AUTOMATION_HUB.value: {
        "label": "Automation Hub",
        "composes": "workflows / taskplan / autonomous / plugins",
    },
    CapabilityId.VOICE_FIRST.value: {
        "label": "Voice-First Desktop",
        "composes": "streaming voice / personality / hands-free config",
    },
    CapabilityId.CONTEXT.value: {
        "label": "Context Engine",
        "composes": "v4 context / reference resolver / session memory",
    },
    CapabilityId.COMPUTER_USE.value: {
        "label": "Computer Use",
        "composes": "neuron.computer_use",
    },
    CapabilityId.AI_PLANNING.value: {
        "label": "AI Planning",
        "composes": "taskplan / autonomous execution",
    },
    CapabilityId.VISION.value: {
        "label": "Vision",
        "composes": "screen understanding / OCR / VLM",
    },
    CapabilityId.MEMORY.value: {
        "label": "Memory",
        "composes": "memory_engine / personality conversation",
    },
    CapabilityId.LEARNING.value: {
        "label": "Learning",
        "composes": "learning_engine habits / procedures",
    },
    CapabilityId.PLUGINS.value: {
        "label": "Plugins",
        "composes": "Plugin SDK builtins + paths",
    },
}


@dataclass
class OsResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OsReport:
    session_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    last_capability: str = ""
    boot_ms: float = 0.0
    dispatch_count: int = 0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
