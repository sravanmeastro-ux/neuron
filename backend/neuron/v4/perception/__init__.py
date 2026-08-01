"""V4.2 PerceptionEngine — observe desktop → DesktopWorldModel."""

from __future__ import annotations

from neuron.v4.perception.element_ids import (
    element_fingerprint_changed,
    looks_sensitive_element,
    normalize_uia_role,
    stable_element_id,
)
from neuron.v4.perception.engine import (
    PerceptionEngine,
    classify_fullscreen,
    get_perception_engine,
    reset_perception_engine,
)
from neuron.v4.perception.screen_diff import cheap_image_fingerprint, diff_desktop_states
from neuron.v4.perception.types import (
    CaptureMeta,
    FullscreenKind,
    PerceptionErrorCode,
    PerceptionFailure,
    PerceptionResult,
    PerceptionSource,
    ScreenDiffResult,
)

__all__ = [
    "PerceptionEngine",
    "PerceptionResult",
    "PerceptionSource",
    "PerceptionErrorCode",
    "PerceptionFailure",
    "CaptureMeta",
    "ScreenDiffResult",
    "FullscreenKind",
    "get_perception_engine",
    "reset_perception_engine",
    "stable_element_id",
    "element_fingerprint_changed",
    "normalize_uia_role",
    "looks_sensitive_element",
    "diff_desktop_states",
    "cheap_image_fingerprint",
    "classify_fullscreen",
]
