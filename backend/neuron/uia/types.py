"""UI element snapshot types for Phase 3."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# Friendly control-type aliases the planner / speech can use
TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "button": ("ButtonControl", "SplitButtonControl", "HyperlinkControl"),
    "text": ("EditControl", "DocumentControl", "TextControl"),
    "textbox": ("EditControl", "DocumentControl"),
    "edit": ("EditControl",),
    "menu": ("MenuControl", "MenuItemControl", "MenuBarControl"),
    "menuitem": ("MenuItemControl",),
    "tab": ("TabControl", "TabItemControl"),
    "tabitem": ("TabItemControl",),
    "list": ("ListControl", "ListItemControl"),
    "listitem": ("ListItemControl",),
    "checkbox": ("CheckBoxControl",),
    "radio": ("RadioButtonControl",),
    "window": ("WindowControl", "PaneControl"),
    "tree": ("TreeControl", "TreeItemControl"),
    "combo": ("ComboBoxControl",),
    "link": ("HyperlinkControl",),
}

# Prefer these when the user says "click X"
CLICK_PREFERRED = (
    "ButtonControl",
    "MenuItemControl",
    "TabItemControl",
    "HyperlinkControl",
    "ListItemControl",
    "TreeItemControl",
    "CheckBoxControl",
    "RadioButtonControl",
    "SplitButtonControl",
)


@dataclass
class ElementInfo:
    name: str = ""
    control_type: str = ""
    automation_id: str = ""
    class_name: str = ""
    value: str = ""
    help_text: str = ""
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    width: int = 0
    height: int = 0
    center_x: int = 0
    center_y: int = 0
    depth: int = 0
    path: str = ""  # parent chain names
    enabled: bool = True
    offscreen: bool = False
    hwnd: int = 0
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def role(self) -> str:
        return (self.control_type or "").replace("Control", "") or "Unknown"

    def bounds_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
            "center_x": self.center_x,
            "center_y": self.center_y,
        }
