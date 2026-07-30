"""Phase 4: intelligent Playwright browser control (DOM/a11y first)."""

from neuron.browser.agent import (
    browser_back,
    browser_click,
    browser_close_tab,
    browser_find_element,
    browser_forward,
    browser_get_elements,
    browser_get_page,
    browser_get_tabs,
    browser_navigate,
    browser_open,
    browser_research,
    browser_scroll,
    browser_search,
    browser_switch_tab,
    browser_type,
)

__all__ = [
    "browser_open",
    "browser_navigate",
    "browser_search",
    "browser_get_page",
    "browser_get_elements",
    "browser_find_element",
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_forward",
    "browser_get_tabs",
    "browser_switch_tab",
    "browser_close_tab",
    "browser_research",
]
