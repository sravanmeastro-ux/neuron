"""V3 WorldState — verified understanding of the computer.

Attempted actions are NOT written into confirmed fields.
open_app("Blender") only updates active_app after observation/verification
shows Blender is actually focused/running.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AttemptedAction:
    """In-flight action — not yet confirmed by observation."""

    action: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    at: float = 0.0
    detail: str = ""


@dataclass
class WorldState:
    """NEURON's current *verified* picture of the desktop."""

    # Verified focus / layout
    active_app: str = ""
    active_window: str = ""
    active_hwnd: int = 0
    active_monitor: int | None = None
    windows: list[dict[str, Any]] = field(default_factory=list)
    monitors: list[dict[str, Any]] = field(default_factory=list)

    # Verified browser
    browser_url: str = ""
    browser_title: str = ""
    scene: str = ""

    # Task (goal text is fine to set on start; outcome is verified)
    current_goal: str = ""
    task_status: str = "idle"  # idle | running | success | failed | interrupted

    # Last verified outcome
    last_action: str = ""
    last_result: str = ""
    last_verified: bool = False
    last_error: str = ""

    # Pending attempt (never treated as confirmed world)
    pending_attempt: AttemptedAction | None = None

    updated_at: float = 0.0
    observation_fingerprint: str = ""

    # ------------------------------------------------------------------ mutate

    def begin_task(self, goal: str) -> None:
        self.current_goal = (goal or "").strip()
        self.task_status = "running"
        self.last_error = ""
        self.pending_attempt = None
        self.updated_at = time.time()

    def record_attempt(self, action: str, args: dict | None = None, detail: str = "") -> None:
        """Mark an action as attempted — does NOT change active_app/window."""
        self.pending_attempt = AttemptedAction(
            action=(action or "").strip(),
            args=_scrub_args(args or {}),
            at=time.time(),
            detail=(detail or "")[:200],
        )
        self.updated_at = time.time()

    def apply_observation(self, world: dict[str, Any] | None) -> bool:
        """
        Update verified fields from a live observation dict
        (verifier.observe_world / ComputerState summary).

        Returns True if focus/window fingerprint changed.
        """
        world = world or {}
        before = self.observation_fingerprint

        app = (
            world.get("active_application")
            or world.get("app")
            or world.get("active_app")
            or ""
        )
        title = (
            world.get("window")
            or world.get("focused_window_title")
            or world.get("title")
            or ""
        )
        hwnd = world.get("hwnd") or world.get("focused_hwnd") or 0
        try:
            hwnd = int(hwnd or 0)
        except (TypeError, ValueError):
            hwnd = 0
        mon = world.get("focused_monitor")
        if mon is None:
            mon = world.get("monitor")
        try:
            mon_i = int(mon) if mon is not None else None
        except (TypeError, ValueError):
            mon_i = None

        if app:
            self.active_app = str(app)[:80]
        if title:
            self.active_window = str(title)[:160]
        if hwnd:
            self.active_hwnd = hwnd
        if mon_i is not None:
            self.active_monitor = mon_i

        wins = world.get("windows") or world.get("open_windows")
        if isinstance(wins, list) and wins:
            self.windows = [_slim_window(w) for w in wins[:24]]

        mons = world.get("monitors")
        if isinstance(mons, list) and mons:
            self.monitors = [_slim_monitor(m) for m in mons[:8]]

        url = world.get("url") or world.get("browser_url") or ""
        if url:
            self.browser_url = str(url)[:240]
        btitle = world.get("browser_title") or ""
        if btitle:
            self.browser_title = str(btitle)[:120]
        scene = world.get("scene") or ""
        if scene:
            self.scene = str(scene)[:40]

        fp = world.get("fingerprint") or world.get("fingerprint_value") or ""
        if not fp:
            fp = f"{self.active_app}|{self.active_window}|{self.active_monitor}|{self.browser_url}"
        self.observation_fingerprint = str(fp)[:120]
        self.updated_at = time.time()
        return bool(before) and before != self.observation_fingerprint

    def confirm_action(
        self,
        *,
        action: str,
        result: str,
        observation: dict[str, Any] | None = None,
        ok: bool = True,
    ) -> None:
        """Verification succeeded (or failed with observation). Updates confirmed fields only from observation."""
        if observation:
            self.apply_observation(observation)
        self.last_action = (action or "").strip()[:80]
        self.last_result = (result or "")[:240]
        self.last_verified = bool(ok)
        if ok:
            self.last_error = ""
        else:
            self.last_error = (result or "")[:240]
        self.pending_attempt = None
        self.updated_at = time.time()

    def fail_action(self, action: str, error: str, observation: dict | None = None) -> None:
        self.confirm_action(
            action=action,
            result=error or "failed",
            observation=observation,
            ok=False,
        )

    def complete_task(self, status: str) -> None:
        st = (status or "idle").strip().lower()
        if st not in ("success", "failed", "interrupted", "idle", "needs_confirm"):
            st = "failed" if "fail" in st else "idle"
        self.task_status = st
        self.pending_attempt = None
        self.updated_at = time.time()

    def clear_task(self) -> None:
        self.current_goal = ""
        self.task_status = "idle"
        self.pending_attempt = None
        self.last_error = ""
        self.updated_at = time.time()

    # ------------------------------------------------------------------ views

    def compact(self, max_chars: int = 500) -> str:
        lines = ["WORLD_STATE (verified):"]
        if self.active_app or self.active_window:
            lines.append(
                f"focus={self.active_app or '?'} | {self.active_window or '?'}"
                f" | monitor={self.active_monitor if self.active_monitor is not None else '?'}"
            )
        if self.browser_url:
            lines.append(f"browser={self.browser_url[:80]}")
        if self.scene:
            lines.append(f"scene={self.scene}")
        if self.current_goal:
            lines.append(f"goal={self.current_goal[:100]} status={self.task_status}")
        if self.pending_attempt:
            lines.append(
                f"PENDING_ATTEMPT (unverified)={self.pending_attempt.action}"
            )
        if self.last_action:
            mark = "verified" if self.last_verified else "failed"
            lines.append(f"last_action={self.last_action} [{mark}] {self.last_result[:80]}")
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _slim_window(w: Any) -> dict[str, Any]:
    if not isinstance(w, dict):
        return {"title": str(w)[:80]}
    return {
        "title": str(w.get("title") or "")[:100],
        "app": str(w.get("app") or w.get("process") or "")[:60],
        "monitor_id": w.get("monitor_id") or w.get("monitor"),
        "hwnd": w.get("hwnd") or 0,
    }


def _slim_monitor(m: Any) -> dict[str, Any]:
    if not isinstance(m, dict):
        return {"id": m}
    return {
        "id": m.get("id") or m.get("monitor_id"),
        "primary": bool(m.get("primary") or m.get("is_primary")),
        "width": m.get("width"),
        "height": m.get("height"),
        "left": m.get("left"),
        "top": m.get("top"),
    }


def _is_sensitive_key(key: str) -> bool:
    k = (key or "").lower()
    return any(
        s in k
        for s in (
            "password", "passwd", "secret", "token", "api_key", "apikey",
            "credential", "ssn", "credit", "cvv", "private_key",
        )
    )


def _scrub_args(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if _is_sensitive_key(str(k)):
            out[str(k)] = "[redacted]"
            continue
        s = str(v)
        if _looks_sensitive_value(s):
            out[str(k)] = "[redacted]"
        else:
            out[str(k)] = s[:80]
    return out


def _looks_sensitive_value(s: str) -> bool:
    low = (s or "").lower()
    if any(x in low for x in ("password=", "Bearer ", "api_key=", "secret=")):
        return True
    # crude credit-card-ish
    digits = "".join(c for c in s if c.isdigit())
    return len(digits) >= 13 and len(digits) <= 19 and len(s) <= 24
