"""V4.3 Semantic Element Resolution — references → UIElementState from DesktopWorldModel."""

from __future__ import annotations

from neuron.v4.resolve.parse import parse_reference
from neuron.v4.resolve.resolver import (
    SemanticElementResolver,
    context_from_engine,
    get_semantic_resolver,
    reset_semantic_resolver,
    resolve,
)
from neuron.v4.resolve.roles import normalize_role, roles_compatible
from neuron.v4.resolve.types import (
    ConfidenceBand,
    ElementCandidate,
    ElementReference,
    ResolutionContext,
    ResolutionResult,
    ResolutionStatus,
    ResolvedElement,
    RevalidateStatus,
)

__all__ = [
    "SemanticElementResolver",
    "ElementReference",
    "ResolutionContext",
    "ElementCandidate",
    "ResolvedElement",
    "ResolutionResult",
    "ResolutionStatus",
    "ConfidenceBand",
    "RevalidateStatus",
    "parse_reference",
    "normalize_role",
    "roles_compatible",
    "get_semantic_resolver",
    "reset_semantic_resolver",
    "resolve",
    "context_from_engine",
]
