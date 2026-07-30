"""Browser tools — Phase 4 Playwright DOM/a11y agent wrappers."""

from __future__ import annotations

from neuron.browser import agent as browser_agent


def browser_open(args: dict):
    return browser_agent.browser_open(args or {})


def browser_navigate(args: dict):
    return browser_agent.browser_navigate(args or {})


def browser_search(args: dict):
    return browser_agent.browser_search(args or {})


def browser_get_page(args: dict):
    return browser_agent.browser_get_page(args or {})


def browser_get_elements(args: dict):
    return browser_agent.browser_get_elements(args or {})


def browser_find_element(args: dict):
    return browser_agent.browser_find_element(args or {})


def browser_click(args: dict):
    return browser_agent.browser_click(args or {})


def browser_type(args: dict):
    return browser_agent.browser_type(args or {})


def browser_scroll(args: dict):
    return browser_agent.browser_scroll(args or {})


def browser_back(args: dict):
    return browser_agent.browser_back(args or {})


def browser_forward(args: dict):
    return browser_agent.browser_forward(args or {})


def browser_get_tabs(args: dict):
    return browser_agent.browser_get_tabs(args or {})


def browser_switch_tab(args: dict):
    return browser_agent.browser_switch_tab(args or {})


def browser_close_tab(args: dict):
    return browser_agent.browser_close_tab(args or {})


def browser_research(args: dict):
    return browser_agent.browser_research(args or {})


# Back-compat alias used by older registry docs
def browser_read_page(args: dict):
    return browser_get_page(args or {})
