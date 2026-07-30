"""Structured tool results for Phase 2 Windows control."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    message: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    method: str = ""  # uia | win32 | pywinauto | startmenu | shell | pyautogui

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state,
            "error": self.error,
            "message": self.message,
            "method": self.method,
        }

    def __str__(self) -> str:
        if self.success:
            return self.message or "Done."
        return self.error or self.message or "Failed."


def ok(message: str, *, state: dict | None = None, method: str = "") -> ToolResult:
    return ToolResult(True, message=message, state=state or {}, error=None, method=method)


def fail(error: str, *, state: dict | None = None, method: str = "") -> ToolResult:
    return ToolResult(False, message=error, state=state or {}, error=error, method=method)
