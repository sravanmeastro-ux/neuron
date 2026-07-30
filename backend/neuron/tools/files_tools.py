"""File / folder tools — Phase 2 wrappers."""

from __future__ import annotations

from neuron.windows import files as file_ops


def open_file(args: dict):
    return file_ops.open_file(args or {})


def open_folder(args: dict):
    return file_ops.open_folder(args or {})


def search_files(args: dict):
    return file_ops.search_files(args or {})
