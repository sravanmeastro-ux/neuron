"""Developer Mode types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DevCapability(str, Enum):
    ANALYZE = "analyze"
    INDEX = "index"
    DEPS = "deps"
    BUILD = "build"
    TEST = "test"
    DIAGNOSTICS = "diagnostics"
    EXPLAIN = "explain"
    BUGS = "bugs"
    REFACTOR = "refactor"
    GIT = "git"
    GITHUB = "github"
    IDE = "ide"
    SCAFFOLD = "scaffold"
    DOCS = "docs"
    STATUS = "status"


@dataclass
class DevResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectIndex:
    root: str = ""
    name: str = ""
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    has_git: bool = False
    has_docker: bool = False
    has_tests: bool = False
    ide_hints: list[str] = field(default_factory=list)
    file_count: int = 0
    top_dirs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
