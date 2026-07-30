"""UI Automation tools — preferred over coordinate clicks (Phase 3)."""

from __future__ import annotations

from neuron.uia import actions as uia_actions


def get_ui_tree(args: dict):
    return uia_actions.get_ui_tree(args or {})


def get_active_window_elements(args: dict):
    return uia_actions.get_active_window_elements(args or {})


def find_ui_element(args: dict):
    return uia_actions.find_ui_element(args or {})


def click_ui_element(args: dict):
    """Semantic click via Element Resolver (DOM → UIA → OCR → Vision)."""
    return uia_actions.click_ui_element(args or {})


def click_element(args: dict):
    """Alias: Agent click("Search") → Element Resolver cascade."""
    from neuron.brain.element_resolver import click as resolver_click
    return resolver_click(args or {})


def find_element(args: dict):
    """Resolve a semantic label without clicking (reports source + coords)."""
    from neuron.brain.element_resolver import find as resolver_find
    return resolver_find(args or {})


def get_element_text(args: dict):
    return uia_actions.get_element_text(args or {})


def get_element_bounds(args: dict):
    return uia_actions.get_element_bounds(args or {})
