"""GitHub Agent orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.github_agent import ops
from neuron.github_agent.detect import classify_github_intent
from neuron.github_agent.types import GitHubCapability, GitHubResult


def dispatch(capability: str, args: dict[str, Any] | None = None) -> GitHubResult:
    args = args or {}
    repo = args.get("repo")

    if capability == GitHubCapability.STATUS.value:
        rem = ops.remote_github(repo)
        return GitHubResult(
            ok=True,
            say=(
                f"GitHub Agent online. Repo={ops.resolve_repo(repo)}; "
                f"gh={'yes' if ops.has_gh() else 'no'}; "
                f"remote={rem.get('slug') or 'none'}."
            ),
            capability=capability,
            data={"remote": rem, "has_gh": ops.has_gh()},
        )

    if capability == GitHubCapability.REPO.value:
        data = ops.analyze_repo(repo)
        commits = ", ".join(data.get("recent_commits") or [])[:200]
        return GitHubResult(
            ok=True,
            say=f"Repo {data.get('repo')} on {data.get('branch')}. Recent: {commits}",
            capability=capability,
            data=data,
        )

    if capability == GitHubCapability.COMMIT.value:
        data = ops.review_commit(repo, str(args.get("rev") or "HEAD"))
        tips = data.get("suggestions") or []
        say = data.get("review") or "Commit review"
        if tips:
            say += " Suggestions: " + "; ".join(tips)
        return GitHubResult(ok=bool(data.get("ok")), say=say, capability=capability, data=data, suggestions=tips)

    if capability == GitHubCapability.PR.value:
        data = ops.review_pr(repo, args.get("number"))
        if not data.get("ok"):
            return GitHubResult(
                ok=False,
                error=data.get("error") or "PR review failed",
                say=data.get("error") or "PR review failed — is gh authenticated and a PR checked out?",
                capability=capability,
                data=data,
            )
        tips = data.get("suggestions") or []
        say = data.get("review") or "PR review"
        if tips:
            say += " " + "; ".join(tips)
        return GitHubResult(ok=True, say=say, capability=capability, data=data, suggestions=tips)

    if capability == GitHubCapability.CONFLICTS.value:
        data = ops.merge_conflicts(repo)
        n = len(data.get("conflicted") or [])
        say = f"{n} conflicted path(s)." if n else "No merge conflicts detected."
        if data.get("advice"):
            say += " " + data["advice"][0]
        return GitHubResult(ok=True, say=say, capability=capability, data=data, suggestions=data.get("advice") or [])

    if capability == GitHubCapability.ISSUE.value:
        title = str(args.get("title") or "Issue from NEURON")
        body = str(args.get("body") or "")
        create = bool(args.get("create"))
        data = ops.generate_issue(repo, title=title, body=body, create=create)
        if create and data.get("created"):
            return GitHubResult(ok=True, say=f"Issue created: {data.get('url')}", acted=True, capability=capability, data=data)
        return GitHubResult(
            ok=True,
            say=f"Issue draft ready: {title}. Confirm to create with gh.",
            capability=capability,
            data=data,
        )

    if capability == GitHubCapability.CHANGELOG.value:
        data = ops.release_notes(repo, args.get("since"))
        return GitHubResult(
            ok=True,
            say=f"Changelog drafted ({data.get('commit_count')} commits, range {data.get('range')}) -> {data.get('path')}",
            capability=capability,
            data=data,
        )

    if capability == GitHubCapability.TAG.value:
        if args.get("create") and args.get("tag"):
            data = ops.create_tag(repo, str(args["tag"]), str(args.get("message") or ""))
            return GitHubResult(
                ok=bool(data.get("ok")),
                say=f"Tag {args['tag']} {'created' if data.get('ok') else 'failed'}",
                acted=bool(data.get("ok")),
                capability=capability,
                data=data,
                error=data.get("stderr") or "",
            )
        data = ops.version_tag(repo, args.get("tag"))
        return GitHubResult(
            ok=True,
            say=f"Suggested tag {data.get('suggested_tag')} (current {data.get('current_tag')}). Confirm to create.",
            capability=capability,
            data=data,
            suggestions=data.get("commands") or [],
        )

    if capability == GitHubCapability.CI.value:
        data = ops.ci_status(repo)
        return GitHubResult(
            ok=bool(data.get("ok")),
            say=data.get("explanation") or data.get("error") or "CI status",
            capability=capability,
            data=data,
            error=data.get("error") or "",
        )

    return GitHubResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False, repo: str | None = None) -> tuple[str, bool, dict]:
    intent = classify_github_intent(text)
    cap = intent.get("capability") or GitHubCapability.REPO.value
    args = dict(intent.get("args") or {})
    if repo:
        args["repo"] = repo
    if confirmed:
        if cap == GitHubCapability.ISSUE.value:
            args["create"] = True
        if cap == GitHubCapability.TAG.value and args.get("tag"):
            args["create"] = True
    result = dispatch(cap, args)
    meta = {"path": "github_agent", "capability": cap, "intent": intent, "result": result.to_dict()}
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "GitHub agent failed.", True, meta
