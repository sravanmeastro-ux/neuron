"""Phase 3: Windows UI Automation understanding."""

from neuron.uia.actions import (
    click_ui_element,
    find_ui_element,
    get_active_window_elements,
    get_element_bounds,
    get_element_text,
    get_ui_tree,
)

__all__ = [
    "get_ui_tree",
    "get_active_window_elements",
    "find_ui_element",
    "click_ui_element",
    "get_element_text",
    "get_element_bounds",
]
