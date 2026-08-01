"""Benchmarks for GitHub Agent."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.github_agent import looks_like_github, orchestrate, dispatch
    from neuron.github_agent.detect import classify_github_intent
    from neuron.github_agent.types import GitHubCapability
    from neuron.github_agent import ops
    from neuron.github_agent.bridge import maybe_handle_github

    assert not looks_like_github("mute")
    assert not looks_like_github("Open Chrome")
    assert looks_like_github("Review my last commit.")
    assert looks_like_github("Generate changelog.")
    assert looks_like_github("Explain why CI failed.")
    assert looks_like_github("Review pull request")
    print("OK detect")

    assert classify_github_intent("Review my last commit.")["capability"] == GitHubCapability.COMMIT.value
    assert classify_github_intent("Generate changelog.")["capability"] == GitHubCapability.CHANGELOG.value
    assert classify_github_intent("Explain why CI failed.")["capability"] == GitHubCapability.CI.value
    print("OK classify")

    analysis = ops.analyze_repo(str(REPO))
    assert analysis.get("ok")
    print(f"OK repo_analysis branch={analysis.get('branch')}")

    rev = ops.review_commit(str(REPO))
    assert rev.get("subject")
    print(f"OK commit_review subject={rev.get('subject', '')[:50]!r}")

    notes = ops.release_notes(str(REPO))
    assert notes.get("markdown") and Path(notes["path"]).is_file()
    print(f"OK changelog commits={notes.get('commit_count')} path={Path(notes['path']).name}")

    conflicts = ops.merge_conflicts(str(REPO))
    assert "conflicted" in conflicts
    print(f"OK conflicts n={len(conflicts.get('conflicted') or [])}")

    tag = ops.version_tag(str(REPO))
    assert tag.get("suggested_tag")
    print(f"OK tag_suggest {tag.get('suggested_tag')}")

    issue = ops.generate_issue(str(REPO), title="Test draft", create=False)
    assert issue.get("draft")
    print("OK issue_draft")

    # CI may fail without gh auth — still should return structured payload
    ci = ops.ci_status(str(REPO))
    print(f"OK ci_status ok={ci.get('ok')} has_gh={ops.has_gh()}")

    say, acted, meta = orchestrate("Review my last commit.", repo=str(REPO))
    assert acted and meta.get("capability") == GitHubCapability.COMMIT.value
    print(f"OK orchestrate say={say[:70]!r}")

    say2, _, meta2 = orchestrate("Generate changelog.", repo=str(REPO))
    assert meta2.get("capability") == GitHubCapability.CHANGELOG.value
    print(f"OK changelog say={say2[:70]!r}")

    assert maybe_handle_github("mute") is None
    hit = maybe_handle_github("Generate changelog.")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("github_status")
    assert tool_registry.get("github_run")
    print("OK tools")

    print("PASS github_agent_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
