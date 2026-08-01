"""NEURON GitHub Agent — repository / PR / CI intelligence (compose-only)."""

from __future__ import annotations

from neuron.github_agent.bridge import maybe_handle_github
from neuron.github_agent.detect import looks_like_github
from neuron.github_agent.orchestrator import dispatch, orchestrate
from neuron.github_agent.types import GitHubCapability


def tool_github_status(args: dict | None = None):
    from neuron.windows.result import ok
    r = dispatch(GitHubCapability.STATUS.value, {"repo": (args or {}).get("repo")})
    return ok(r.say, state=r.to_dict(), method="github_agent")


def tool_github_run(args: dict | None = None):
    from neuron.windows.result import ok, fail
    args = args or {}
    text = str(args.get("request") or args.get("goal") or args.get("query") or "").strip()
    cap = str(args.get("capability") or "").strip()
    confirmed = bool(args.get("confirmed", False))
    repo = args.get("repo")
    if cap:
        payload = {k: v for k, v in args.items() if k not in ("capability", "request", "confirmed")}
        if confirmed and cap in ("issue_generation", "version_tagging"):
            payload["create"] = True
        r = dispatch(cap, payload)
        return ok(r.say, state=r.to_dict(), method="github_agent") if r.ok else fail(r.error or r.say, state=r.to_dict())
    if not text:
        return fail("Need request or capability.")
    say, acted, meta = orchestrate(text, confirmed=confirmed, repo=repo)
    return ok(say, state=meta, method="github_agent") if acted else fail(say, state=meta)


__all__ = [
    "maybe_handle_github",
    "looks_like_github",
    "orchestrate",
    "dispatch",
    "GitHubCapability",
    "tool_github_status",
    "tool_github_run",
]
