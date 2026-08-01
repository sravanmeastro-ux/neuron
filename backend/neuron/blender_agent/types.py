"""Blender Agent types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class BlenderCapability(str, Enum):
    CREATE = "create"
    IMPORT = "import"
    EXPORT = "export"
    MATERIAL = "material"
    GEONODES = "geometry_nodes"
    RIGGING = "rigging"
    ANIMATION = "animation"
    LIGHTING = "lighting"
    RENDER = "render"
    PHYSICS = "physics"
    CAMERA = "camera"
    TEXTURE = "texture"
    ASSETS = "assets"
    TOPOLOGY = "topology"
    OPEN = "open"
    STATUS = "status"
    RUN_SCRIPT = "run_script"


@dataclass
class BlenderResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    script_path: str = ""
    output_path: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
