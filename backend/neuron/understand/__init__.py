"""NEURON Intent Understanding Engine — semantic layer before FastIntentRouter."""

from __future__ import annotations

from neuron.understand.engine import understand, understand_for_router
from neuron.understand.types import EntitySpan, SemanticUnderstanding
from neuron.understand import context_mem

__all__ = [
    "understand",
    "understand_for_router",
    "EntitySpan",
    "SemanticUnderstanding",
    "context_mem",
]
