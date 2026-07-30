"""Window / monitor tools — Phase 2 + Phase 10 wrappers."""

from __future__ import annotations

from neuron.windows import winops


def get_monitors(args: dict):
    return winops.get_monitors(args or {})


def get_windows(args: dict):
    return winops.get_windows(args or {})


def get_windows_by_monitor(args: dict):
    return winops.get_windows_by_monitor(args or {})


def get_active_window(args: dict):
    return winops.get_active_window(args or {})


def move_window(args: dict):
    return winops.move_window(args or {})


def move_window_to_monitor(args: dict):
    return winops.move_window_to_monitor(args or {})


def resize_window(args: dict):
    return winops.resize_window(args or {})
