"""V4.8 capability descriptors — semantic index over ToolRegistry."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CapabilityDomain(str, Enum):
    OS = "OS"
    APP = "APP"
    WINDOW = "WINDOW"
    MONITOR = "MONITOR"
    KEYBOARD = "KEYBOARD"
    MOUSE = "MOUSE"
    UI = "UI"
    BROWSER = "BROWSER"
    YOUTUBE = "YOUTUBE"
    MEDIA = "MEDIA"
    FILE = "FILE"
    BLENDER = "BLENDER"
    SYSTEM = "SYSTEM"
    INTEGRATION = "INTEGRATION"
    PROCEDURE = "PROCEDURE"
    UNKNOWN = "UNKNOWN"


class CapabilityKind(str, Enum):
    ATOMIC = "ATOMIC"
    COMPOSITE = "COMPOSITE"
    PROCEDURE = "PROCEDURE"


@dataclass
class CapabilityDescriptor:
    capability_id: str
    name: str = ""
    domain: CapabilityDomain = CapabilityDomain.UNKNOWN
    description: str = ""
    tool_name: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    kind: CapabilityKind = CapabilityKind.ATOMIC
    risk_hint: str = "safe"
    input_schema: dict[str, Any] = field(default_factory=dict)
    verification_kind: str = ""
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    determinism: str = "deterministic"
    supports_mock: bool = True
    supports_live: bool = True
    planner_enabled: bool = True
    fast_path_enabled: bool = False
    recovery_enabled: bool = True
    router_id: str = ""
    control_methods: list[str] = field(default_factory=list)
    intent_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name or self.capability_id,
            "domain": self.domain.value,
            "description": self.description[:160],
            "tool_name": self.tool_name,
            "aliases": list(self.aliases)[:8],
            "kind": self.kind.value,
            "risk_hint": self.risk_hint,
            "verification_kind": self.verification_kind,
            "preconditions": list(self.preconditions)[:6],
            "planner_enabled": self.planner_enabled,
            "fast_path_enabled": self.fast_path_enabled,
            "recovery_enabled": self.recovery_enabled,
            "router_id": self.router_id,
            "intent_keys": list(self.intent_keys)[:8],
        }


@dataclass
class CapabilityResolution:
    ok: bool
    capability: CapabilityDescriptor | None = None
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    risk: str = "safe"
    verification_kind: str = ""
    candidates: list[str] = field(default_factory=list)
    unsupported: bool = False
    needs_confirm: bool = False
    latency_ms: float = 0.0

    def to_grounded_action(self, *, intent: str = "", expected_result: str = ""):
        from neuron.v4.plan.types import GroundedAction

        if not self.ok or not self.tool:
            return None
        return GroundedAction(
            tool=self.tool,
            arguments=dict(self.args),
            expected_result=expected_result or self.verification_kind,
            risk=self.risk,
            capability_id=self.capability.capability_id if self.capability else self.tool,
            reason=intent,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "args": {k: str(v)[:80] for k, v in list(self.args.items())[:12]},
            "reason": self.reason[:160],
            "risk": self.risk,
            "verification_kind": self.verification_kind,
            "unsupported": self.unsupported,
            "needs_confirm": self.needs_confirm,
            "candidates": self.candidates[:8],
            "capability": self.capability.to_dict() if self.capability else None,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class CapabilityStats:
    attempts: int = 0
    exec_ok: int = 0
    verify_success: int = 0
    verify_uncertain: int = 0
    verify_failure: int = 0
    recovery_required: int = 0
    latency_ms_total: float = 0.0

    def note(
        self,
        *,
        exec_ok: bool | None = None,
        verify: str = "",
        latency_ms: float = 0.0,
        recovery: bool = False,
    ) -> None:
        self.attempts += 1
        self.latency_ms_total += latency_ms
        if exec_ok is True:
            self.exec_ok += 1
        v = (verify or "").upper()
        if v == "SUCCESS":
            self.verify_success += 1
        elif v == "UNCERTAIN":
            self.verify_uncertain += 1
        elif v == "FAILURE":
            self.verify_failure += 1
        if recovery:
            self.recovery_required += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "exec_ok": self.exec_ok,
            "verify_success": self.verify_success,
            "verify_uncertain": self.verify_uncertain,
            "verify_failure": self.verify_failure,
            "recovery_required": self.recovery_required,
            "avg_latency_ms": round(self.latency_ms_total / max(1, self.attempts), 2),
        }


@dataclass
class FailureMemory:
    entries: list[tuple[str, float]] = field(default_factory=list)
    ttl_s: float = 120.0
    max_n: int = 32

    def note(self, key: str) -> None:
        now = time.time()
        self.entries.append((key, now))
        self.entries = [(k, t) for k, t in self.entries if now - t <= self.ttl_s][-self.max_n :]

    def recently_failed(self, key: str) -> bool:
        now = time.time()
        return any(k == key and now - t <= self.ttl_s for k, t in self.entries)

    def clear(self) -> None:
        self.entries.clear()


__all__ = [
    "CapabilityDomain",
    "CapabilityKind",
    "CapabilityDescriptor",
    "CapabilityResolution",
    "CapabilityStats",
    "FailureMemory",
]
