"""Plugin SDK types — manifest, actions, intents, permissions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass
class PermissionSpec:
    risk_ceiling: str = "confirm"  # safe | confirm | high
    control_methods: list[str] = field(default_factory=lambda: ["api"])
    planner_visible: bool = True
    allow_shell: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionSpec:
    name: str
    description: str = ""
    args_schema: dict[str, str] = field(default_factory=dict)
    risk: str = "safe"
    handler: str = ""  # "module:attr" relative to plugin package
    aliases: list[str] = field(default_factory=list)
    control_methods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntentSpec:
    id: str
    aliases: list[str] = field(default_factory=list)
    prefer: list[str] = field(default_factory=list)  # action names

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConfigSpec:
    schema: dict[str, Any] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DependencySpec:
    neuron: str = ">=4.0"
    tools: list[str] = field(default_factory=list)
    python: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)  # other plugin ids

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PluginManifest:
    id: str
    version: str = "1.0.0"
    name: str = ""
    description: str = ""
    docs: str = "README.md"
    author: str = "NEURON"
    api_version: str = "1"  # Plugin Host API version this package targets
    homepage: str = ""
    permissions: PermissionSpec = field(default_factory=PermissionSpec)
    config: ConfigSpec = field(default_factory=ConfigSpec)
    dependencies: DependencySpec = field(default_factory=DependencySpec)
    intents: list[IntentSpec] = field(default_factory=list)
    actions: list[ActionSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name or self.id,
            "description": self.description,
            "docs": self.docs,
            "author": self.author,
            "api_version": self.api_version,
            "homepage": self.homepage,
            "permissions": self.permissions.to_dict(),
            "config": self.config.to_dict(),
            "dependencies": self.dependencies.to_dict(),
            "intents": [i.to_dict() for i in self.intents],
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PluginManifest":
        perms = d.get("permissions") or {}
        conf = d.get("config") or {}
        deps = d.get("dependencies") or {}
        return cls(
            id=str(d.get("id") or ""),
            version=str(d.get("version") or "1.0.0"),
            name=str(d.get("name") or d.get("id") or ""),
            description=str(d.get("description") or ""),
            docs=str(d.get("docs") or "README.md"),
            author=str(d.get("author") or "NEURON"),
            api_version=str(d.get("api_version") or "1"),
            homepage=str(d.get("homepage") or ""),
            permissions=PermissionSpec(
                risk_ceiling=str(perms.get("risk_ceiling") or "confirm"),
                control_methods=list(perms.get("control_methods") or ["api"]),
                planner_visible=bool(perms.get("planner_visible", True)),
                allow_shell=bool(perms.get("allow_shell", False)),
            ),
            config=ConfigSpec(
                schema=dict(conf.get("schema") or {}),
                defaults=dict(conf.get("defaults") or {}),
            ),
            dependencies=DependencySpec(
                neuron=str(deps.get("neuron") or ">=4.0"),
                tools=list(deps.get("tools") or []),
                python=list(deps.get("python") or []),
                plugins=list(deps.get("plugins") or []),
            ),
            intents=[
                IntentSpec(
                    id=str(i.get("id") or ""),
                    aliases=list(i.get("aliases") or []),
                    prefer=list(i.get("prefer") or []),
                )
                for i in (d.get("intents") or [])
            ],
            actions=[
                ActionSpec(
                    name=str(a.get("name") or ""),
                    description=str(a.get("description") or ""),
                    args_schema={str(k): str(v) for k, v in (a.get("args_schema") or {}).items()},
                    risk=str(a.get("risk") or "safe"),
                    handler=str(a.get("handler") or "actions:default"),
                    aliases=list(a.get("aliases") or []),
                    control_methods=list(a.get("control_methods") or []),
                )
                for a in (d.get("actions") or [])
            ],
        )


Handler = Callable[[dict], Any]


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    root: str
    handlers: dict[str, Handler] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    registered_tools: list[str] = field(default_factory=list)
    enabled: bool = True
    load_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.manifest.id,
            "version": self.manifest.version,
            "name": self.manifest.name,
            "enabled": self.enabled,
            "root": self.root,
            "tools": list(self.registered_tools),
            "intents": [i.id for i in self.manifest.intents],
            "load_error": self.load_error,
            "docs": self.manifest.docs,
        }
