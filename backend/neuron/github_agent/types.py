"""GitHub Agent types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class GitHubCapability(str, Enum):
    REPO = "repo_analysis"
    COMMIT = "commit_review"
    PR = "pr_review"
    CONFLICTS = "merge_conflicts"
    ISSUE = "issue_generation"
    CHANGELOG = "release_notes"
    TAG = "version_tagging"
    CI = "ci_monitoring"
    STATUS = "status"


@dataclass
class GitHubResult:
    ok: bool = True
    say: str = ""
    acted: bool = False
    capability: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
