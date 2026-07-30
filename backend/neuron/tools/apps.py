"""App process tools — Phase 2 wrappers."""

from __future__ import annotations

from neuron.windows import apps as wapps


def get_running_apps(args: dict):
    return wapps.get_running_apps(args or {})


def focus_app(args: dict):
    return wapps.focus_app(args or {})


def open_app(args: dict):
    return wapps.open_app(args or {})


def close_app(args: dict):
    return wapps.close_app(args or {})


def minimize_app(args: dict):
    return wapps.minimize_app(args or {})


def maximize_app(args: dict):
    return wapps.maximize_app(args or {})
