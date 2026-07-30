"""Phase 2: Windows computer control (UIA → pywinauto → input fallback)."""

from neuron.windows import apps, files, input_ops, winops
from neuron.windows.result import ToolResult

__all__ = [
    "ToolResult",
    "apps",
    "winops",
    "input_ops",
    "files",
]
