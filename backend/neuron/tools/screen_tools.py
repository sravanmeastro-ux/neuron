"""Screen capture / OCR / analyze tools (Phase 5)."""

from __future__ import annotations

from neuron.perception import capture_ops, pipeline
from neuron.perception import ocr as ocr_mod


def capture_screen(args: dict):
    return capture_ops.capture_screen(args or {})


def capture_monitor(args: dict):
    return capture_ops.capture_monitor(args or {})


def get_cursor_position(args: dict):
    return capture_ops.get_cursor_position(args or {})


def get_active_window_screenshot(args: dict):
    return capture_ops.get_active_window_screenshot(args or {})


def ocr_image(args: dict):
    return ocr_mod.ocr_image(args or {})


def detect_text_regions(args: dict):
    return ocr_mod.detect_text_regions(args or {})


def ocr_screen(args: dict):
    return ocr_mod.ocr_image(args or {})


def analyze_screen(args: dict):
    return pipeline.analyze_screen(args or {})


def get_screen_context(args: dict):
    return pipeline.get_screen_context(args or {})
