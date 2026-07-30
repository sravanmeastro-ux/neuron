"""Local perception: capture, OCR, ScreenContext pipeline."""

from neuron.perception.capture_ops import (
    capture_monitor,
    capture_screen,
    get_active_window_screenshot,
    get_cursor_position,
)
from neuron.perception.ocr import detect_text_regions, ocr_image, read_screen
from neuron.perception.pipeline import analyze_screen, build_screen_context, get_screen_context
from neuron.perception.screen_context import ScreenContext

__all__ = [
    "ScreenContext",
    "build_screen_context",
    "get_screen_context",
    "analyze_screen",
    "capture_screen",
    "capture_monitor",
    "get_cursor_position",
    "get_active_window_screenshot",
    "ocr_image",
    "detect_text_regions",
    "read_screen",
]
