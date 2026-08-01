"""Workflow types — steps, control flow, variables."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Step kinds recorded or authored:
# mouse | key | hotkey | type | app | focus | clipboard | browser | wait | tool | set | loop | if
STEP_KINDS = frozenset({
    "mouse",
    "key",
    "hotkey",
    "type",
    "app",
    "focus",
    "clipboard",
    "browser",
    "wait",
    "tool",
    "set",
    "loop",
    "if",
})


@dataclass
class WorkflowStep:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)
    # Nested control-flow bodies
    steps: list["WorkflowStep"] = field(default_factory=list)
    else_steps: list["WorkflowStep"] = field(default_factory=list)
    # Metadata from recording
    t: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "args": dict(self.args or {})}
        if self.steps:
            d["steps"] = [s.to_dict() for s in self.steps]
        if self.else_steps:
            d["else_steps"] = [s.to_dict() for s in self.else_steps]
        if self.t:
            d["t"] = self.t
        if self.note:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "WorkflowStep":
        d = d or {}
        return cls(
            kind=str(d.get("kind") or "wait"),
            args=dict(d.get("args") or {}),
            steps=[cls.from_dict(s) for s in (d.get("steps") or [])],
            else_steps=[cls.from_dict(s) for s in (d.get("else_steps") or [])],
            t=float(d.get("t") or 0.0),
            note=str(d.get("note") or ""),
        )


@dataclass
class Workflow:
    id: str
    name: str = ""
    description: str = ""
    version: int = 1
    variables: dict[str, Any] = field(default_factory=dict)
    steps: list[WorkflowStep] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    tags: list[str] = field(default_factory=list)
    # Channels captured during recording
    channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "description": self.description,
            "version": self.version,
            "variables": dict(self.variables or {}),
            "steps": [s.to_dict() for s in self.steps],
            "created": self.created,
            "updated": self.updated,
            "tags": list(self.tags or []),
            "channels": list(self.channels or []),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Workflow":
        d = d or {}
        return cls(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or d.get("id") or ""),
            description=str(d.get("description") or ""),
            version=int(d.get("version") or 1),
            variables=dict(d.get("variables") or {}),
            steps=[WorkflowStep.from_dict(s) for s in (d.get("steps") or [])],
            created=str(d.get("created") or ""),
            updated=str(d.get("updated") or ""),
            tags=list(d.get("tags") or []),
            channels=list(d.get("channels") or []),
        )

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "steps": len(self.steps),
            "variables": list(self.variables.keys()),
            "channels": list(self.channels),
            "updated": self.updated,
        }
