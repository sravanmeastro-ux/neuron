"""Canonical closed-loop step schema for NEURON AgentLoop.

Every executable step carries:
  action, target, expected_result, timeout, retry_limit

Legacy plans with only {action, args} remain valid — missing fields
are filled with sensible defaults during normalize.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_TIMEOUT = 45.0
DEFAULT_RETRY_LIMIT = 2


@dataclass
class Step:
    """One verified unit of work inside the agent loop."""

    action: str
    args: dict[str, Any] = field(default_factory=dict)
    target: str = ""
    expected_result: str = ""
    timeout: float = DEFAULT_TIMEOUT
    retry_limit: int = DEFAULT_RETRY_LIMIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "args": dict(self.args or {}),
            "target": self.target or "",
            "expected_result": self.expected_result or "",
            "timeout": float(self.timeout),
            "retry_limit": int(self.retry_limit),
        }

    @classmethod
    def from_dict(cls, raw: dict | None, *, default_timeout: float = DEFAULT_TIMEOUT,
                  default_retry: int = DEFAULT_RETRY_LIMIT) -> "Step | None":
        if not isinstance(raw, dict):
            return None
        action = str(
            raw.get("action") or raw.get("tool") or raw.get("name") or raw.get("fn") or ""
        ).strip()
        if not action:
            return None
        args = raw.get("args") or raw.get("arguments") or raw.get("params") or {}
        if not isinstance(args, dict):
            args = {}

        target = str(
            raw.get("target")
            or args.get("name")
            or args.get("application")
            or args.get("site")
            or args.get("url")
            or args.get("text")
            or args.get("query")
            or args.get("title")
            or ""
        ).strip()

        expected = str(
            raw.get("expected_result")
            or raw.get("expect")
            or raw.get("expected")
            or ""
        ).strip()

        timeout = raw.get("timeout", raw.get("timeout_seconds", default_timeout))
        try:
            timeout_f = float(timeout if timeout is not None else default_timeout)
        except (TypeError, ValueError):
            timeout_f = float(default_timeout)
        if timeout_f <= 0:
            timeout_f = float(default_timeout)

        retry = raw.get("retry_limit", raw.get("retries", default_retry))
        try:
            retry_i = int(retry if retry is not None else default_retry)
        except (TypeError, ValueError):
            retry_i = int(default_retry)
        if retry_i < 0:
            retry_i = 0

        return cls(
            action=action,
            args=dict(args),
            target=target,
            expected_result=expected,
            timeout=timeout_f,
            retry_limit=retry_i,
        )


def infer_expected_result(action: str, args: dict | None, target: str = "") -> str:
    """Heuristic expected_result when the planner omitted one."""
    action = (action or "").strip()
    args = args or {}
    name = (target or args.get("name") or args.get("application") or "").strip()
    site = (args.get("site") or args.get("url") or "").strip()
    query = (args.get("query") or args.get("q") or "").strip()

    if action in ("open_app", "focus_app"):
        return f"app '{name or 'target'}' is running or has a visible window"
    if action == "close_app":
        return f"app '{name or 'target'}' window is gone"
    if action in ("browser_open", "open_website", "browser_navigate"):
        return f"browser URL reflects '{site or name or 'destination'}'"
    if action in ("browser_search", "search_site"):
        return f"search results for '{query or name}' are visible"
    if action == "youtube_home":
        return "browser is on youtube.com"
    if action in ("browser_click", "click_ui_element", "click_element"):
        return f"clicked '{name or args.get('text') or args.get('index') or 'target'}' successfully"
    if action in ("move_window", "move_window_to_monitor"):
        mon = args.get("monitor") or args.get("monitor_id") or args.get("screen") or ""
        return f"window '{name or args.get('title') or 'target'}' is on monitor {mon}".strip()
    if action in ("analyze_screen", "get_screen_context", "describe_screen"):
        return "screen observation captured"
    if action:
        return f"{action} completed without error"
    return "step succeeded"


def enrich_step_dict(
    step: dict,
    *,
    default_timeout: float = DEFAULT_TIMEOUT,
    default_retry: int = DEFAULT_RETRY_LIMIT,
) -> dict[str, Any]:
    """Ensure a step dict has all closed-loop fields. Mutates a copy."""
    s = Step.from_dict(step, default_timeout=default_timeout, default_retry=default_retry)
    if s is None:
        return dict(step) if isinstance(step, dict) else {}
    if not s.expected_result:
        s.expected_result = infer_expected_result(s.action, s.args, s.target)
    return s.to_dict()
