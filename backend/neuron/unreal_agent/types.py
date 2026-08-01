"""Unreal Agent types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class UnrealCapability(str, Enum):
    BLUEPRINT = "blueprint"
    CPP = "cpp"
    MATERIAL = "material"
    NIAGARA = "niagara"
    LANDSCAPE = "landscape"
    ANIMATION = "animation"
    SEQUENCER = "sequencer"
    LIGHTING = "lighting"
    OPTIMIZATION = "optimization"
    PACKAGING = "packaging"
    BUILD = "build"
    CRASH = "crash"
    PROJECT = "project"
    CHARACTER = "character"
    OPEN = "open"
    STATUS = "status"
    RUN_SCRIPT = "run_script"


@dataclass
class UnrealResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    artifact_path: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    dry_run: bool = False
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
