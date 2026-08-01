"""git + gh CLI helpers for GitHub intelligence."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def default_repo() -> Path:
    here = Path(__file__).resolve()
    # backend/neuron/github_agent -> repo root (fillo jarvis)
    for p in (Path.cwd(), here.parents[3], here.parents[2]):
        if (p / ".git").exists():
            return p.resolve()
    return Path.cwd().resolve()


def resolve_repo(path: str | None = None) -> Path:
    if path:
        p = Path(path).expanduser().resolve()
        return p if p.is_dir() else p.parent
    return default_repo()


def _run(args: list[str], cwd: Path, timeout: float = 45.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{args[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def has_gh() -> bool:
    return shutil.which("gh") is not None


def git(args: list[str], repo: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    code, out, err = _run(["git", *args], cwd)
    return {"ok": code == 0, "code": code, "stdout": out.strip(), "stderr": err.strip(), "repo": str(cwd)}


def gh(args: list[str], repo: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    if not has_gh():
        return {"ok": False, "code": 127, "stdout": "", "stderr": "gh CLI not found", "repo": str(cwd)}
    code, out, err = _run(["gh", *args], cwd)
    return {"ok": code == 0, "code": code, "stdout": out.strip(), "stderr": err.strip(), "repo": str(cwd)}


def remote_github(repo: str | None = None) -> dict[str, Any]:
    r = git(["remote", "-v"], repo)
    urls = []
    for line in (r.get("stdout") or "").splitlines():
        m = re.search(r"(https://github\.com/[^/\s]+/[^/\s]+|git@github\.com:[^/\s]+/[^/\s]+)", line)
        if m:
            u = m.group(1).rstrip(".git")
            urls.append(u)
    slug = None
    if urls:
        u = urls[0]
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+)$", u)
        if m:
            slug = f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    return {"ok": r.get("ok"), "urls": list(dict.fromkeys(urls)), "slug": slug, "repo": r.get("repo")}


def analyze_repo(repo: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], str(cwd))
    status = git(["status", "--short", "--branch"], str(cwd))
    log = git(["log", "-5", "--oneline", "--decorate"], str(cwd))
    rem = remote_github(str(cwd))
    # language-ish from tree
    exts: dict[str, int] = {}
    try:
        for p in cwd.rglob("*"):
            if not p.is_file() or ".git" in p.parts or "node_modules" in p.parts:
                continue
            suf = p.suffix.lower()
            if suf:
                exts[suf] = exts.get(suf, 0) + 1
            if sum(exts.values()) > 5000:
                break
    except Exception:
        pass
    top_ext = sorted(exts.items(), key=lambda x: -x[1])[:8]
    return {
        "ok": True,
        "repo": str(cwd),
        "branch": branch.get("stdout"),
        "status": status.get("stdout"),
        "recent_commits": (log.get("stdout") or "").splitlines(),
        "github": rem,
        "top_extensions": top_ext,
    }


def review_commit(repo: str | None = None, rev: str = "HEAD") -> dict[str, Any]:
    cwd = resolve_repo(repo)
    meta = git(["show", "-s", "--format=%H%n%s%n%an%n%ae%n%ci%n%b", rev], str(cwd))
    lines = (meta.get("stdout") or "").splitlines()
    stat = git(["show", "--stat", "--oneline", "-1", rev], str(cwd))
    name_status = git(["show", "--name-status", "--format=", rev], str(cwd))
    files = []
    for line in (name_status.get("stdout") or "").splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            files.append({"status": parts[0], "path": parts[1]})
    subject = lines[1] if len(lines) > 1 else ""
    suggestions = []
    low = subject.lower()
    if len(subject) < 10:
        suggestions.append("Commit subject is very short — consider a clearer why-focused message.")
    if subject and subject[0].islower():
        suggestions.append("Consider Capitalizing the commit subject.")
    if any(f["path"].endswith((".env", "credentials.json", "id_rsa")) for f in files):
        suggestions.append("Possible secret file in commit — verify before pushing.")
    if sum(1 for f in files if f["status"].startswith("A")) > 40:
        suggestions.append("Large add set — consider splitting the commit.")
    review = (
        f"Commit {lines[0][:8] if lines else '?'}: {subject} "
        f"by {lines[2] if len(lines) > 2 else '?'} on {lines[4] if len(lines) > 4 else '?'}."
    )
    return {
        "ok": bool(meta.get("ok")),
        "hash": lines[0] if lines else "",
        "subject": subject,
        "author": lines[2] if len(lines) > 2 else "",
        "email": lines[3] if len(lines) > 3 else "",
        "date": lines[4] if len(lines) > 4 else "",
        "body": "\n".join(lines[5:]).strip() if len(lines) > 5 else "",
        "stat": stat.get("stdout"),
        "files": files[:80],
        "review": review,
        "suggestions": suggestions,
        "repo": str(cwd),
    }


def review_pr(repo: str | None = None, number: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    if number:
        data = gh(["pr", "view", str(number), "--json", "number,title,body,author,state,commits,files,reviews,statusCheckRollup,url"], str(cwd))
    else:
        data = gh(["pr", "view", "--json", "number,title,body,author,state,commits,files,reviews,statusCheckRollup,url"], str(cwd))
    if not data.get("ok"):
        # Fallback: list PRs
        listing = gh(["pr", "list", "--limit", "5", "--json", "number,title,state,author"], str(cwd))
        return {
            "ok": False,
            "error": data.get("stderr") or "No PR checked out / gh failed",
            "listing": listing.get("stdout"),
            "repo": str(cwd),
        }
    try:
        pr = json.loads(data["stdout"] or "{}")
    except Exception:
        pr = {"raw": data.get("stdout")}
    checks = pr.get("statusCheckRollup") or []
    failed = [c for c in checks if isinstance(c, dict) and str(c.get("conclusion") or c.get("state") or "").upper() in ("FAILURE", "FAILED", "ERROR")]
    suggestions = []
    if failed:
        suggestions.append(f"{len(failed)} failing check(s) — inspect CI logs before merge.")
    title = pr.get("title") or ""
    if title and title.lower().startswith("wip"):
        suggestions.append("PR marked WIP — avoid merge until ready.")
    files = pr.get("files") or []
    if isinstance(files, list) and len(files) > 30:
        suggestions.append("Large PR — consider splitting for reviewability.")
    say = f"PR #{pr.get('number')}: {title} [{pr.get('state')}] — {pr.get('url') or ''}"
    return {"ok": True, "pr": pr, "failed_checks": failed, "suggestions": suggestions, "review": say, "repo": str(cwd)}


def merge_conflicts(repo: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    # Unmerged paths
    unmerged = git(["diff", "--name-only", "--diff-filter=U"], str(cwd))
    files = [f for f in (unmerged.get("stdout") or "").splitlines() if f.strip()]
    # Also detect conflict markers in common merge state
    status = git(["status", "--short"], str(cwd))
    conflicted = files[:]
    for line in (status.get("stdout") or "").splitlines():
        if line.startswith("UU ") or line.startswith("AA ") or line.startswith("DD "):
            conflicted.append(line[3:].strip())
    conflicted = list(dict.fromkeys(conflicted))
    advice = []
    if conflicted:
        advice = [
            f"Open and resolve: {conflicted[0]}",
            "Search for <<<<<<< / ======= / >>>>>>> markers.",
            "After fixing: git add <files> && git commit (or git merge --continue).",
            "Prefer keeping tests green on both sides of the conflict.",
        ]
    else:
        advice = ["No unmerged paths detected. If rebasing, check git status for 'rebase in progress'."]
    return {
        "ok": True,
        "conflicted": conflicted,
        "status": status.get("stdout"),
        "advice": advice,
        "repo": str(cwd),
    }


def generate_issue(repo: str | None = None, title: str = "", body: str = "", *, create: bool = False) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    if not title:
        title = "Issue from NEURON"
    if not body:
        body = "## Summary\n\nDescribe the problem.\n\n## Steps to reproduce\n\n1.\n\n## Expected\n\n## Actual\n"
    draft = {"title": title, "body": body}
    if not create:
        return {"ok": True, "draft": draft, "created": False, "repo": str(cwd)}
    r = gh(["issue", "create", "--title", title, "--body", body], str(cwd))
    return {"ok": r.get("ok"), "draft": draft, "created": bool(r.get("ok")), "url": r.get("stdout"), "stderr": r.get("stderr"), "repo": str(cwd)}


def release_notes(repo: str | None = None, since: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    # Commits since last tag or since arg
    last_tag = git(["describe", "--tags", "--abbrev=0"], str(cwd))
    range_spec = since
    if not range_spec:
        if last_tag.get("ok") and last_tag.get("stdout"):
            range_spec = f"{last_tag['stdout']}..HEAD"
        else:
            range_spec = "HEAD~20..HEAD"
    log = git(["log", range_spec, "--pretty=format:%s (%h)"], str(cwd))
    commits = [c for c in (log.get("stdout") or "").splitlines() if c.strip()]
    features, fixes, other = [], [], []
    for c in commits:
        low = c.lower()
        if low.startswith("feat") or "add " in low:
            features.append(c)
        elif low.startswith("fix") or "bug" in low:
            fixes.append(c)
        else:
            other.append(c)
    lines = ["# Changelog", ""]
    if features:
        lines += ["## Features", *[f"- {x}" for x in features], ""]
    if fixes:
        lines += ["## Fixes", *[f"- {x}" for x in fixes], ""]
    if other:
        lines += ["## Other", *[f"- {x}" for x in other[:30]], ""]
    md = "\n".join(lines) if commits else "# Changelog\n\n_No commits in range._\n"
    # Persist artifact
    out = Path(__file__).resolve().parents[2] / "data" / "github_agent"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "CHANGELOG_DRAFT.md"
    path.write_text(md, encoding="utf-8")
    return {
        "ok": True,
        "range": range_spec,
        "last_tag": last_tag.get("stdout") if last_tag.get("ok") else None,
        "markdown": md,
        "path": str(path),
        "commit_count": len(commits),
        "repo": str(cwd),
    }


def version_tag(repo: str | None = None, tag: str | None = None, *, push: bool = False) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    last = git(["describe", "--tags", "--abbrev=0"], str(cwd))
    suggested = tag
    if not suggested:
        # bump patch on vX.Y.Z or default v0.1.0
        cur = last.get("stdout") if last.get("ok") else ""
        m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", cur or "")
        if m:
            suggested = f"v{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}"
        else:
            suggested = "v0.1.0"
    # Do not create unless tag explicitly provided with push/create semantics — return plan by default
    return {
        "ok": True,
        "current_tag": last.get("stdout") if last.get("ok") else None,
        "suggested_tag": suggested,
        "commands": [f"git tag -a {suggested} -m \"Release {suggested}\"", f"git push origin {suggested}"],
        "pushed": False,
        "repo": str(cwd),
        "note": "Tagging is suggested only; pass create via tool with confirmed to run.",
    }


def create_tag(repo: str | None = None, tag: str = "", message: str = "") -> dict[str, Any]:
    cwd = resolve_repo(repo)
    if not tag:
        return {"ok": False, "error": "Need tag name"}
    msg = message or f"Release {tag}"
    r = git(["tag", "-a", tag, "-m", msg], str(cwd))
    return {"ok": r.get("ok"), "tag": tag, "stderr": r.get("stderr"), "repo": str(cwd)}


def ci_status(repo: str | None = None) -> dict[str, Any]:
    cwd = resolve_repo(repo)
    # Prefer gh run list
    runs = gh(["run", "list", "--limit", "5", "--json", "databaseId,name,status,conclusion,event,headBranch,url,displayTitle"], str(cwd))
    if not runs.get("ok"):
        # Fallback: pr checks
        checks = gh(["pr", "checks"], str(cwd))
        return {
            "ok": False,
            "error": runs.get("stderr") or "gh run list failed",
            "pr_checks": checks.get("stdout"),
            "repo": str(cwd),
        }
    try:
        items = json.loads(runs["stdout"] or "[]")
    except Exception:
        items = []
    failed = [i for i in items if str(i.get("conclusion") or "").lower() == "failure"]
    in_progress = [i for i in items if str(i.get("status") or "").lower() in ("in_progress", "queued")]
    explanation = ""
    if failed:
        fid = failed[0].get("databaseId")
        view = gh(["run", "view", str(fid), "--log-failed"], str(cwd)) if fid else {"stdout": ""}
        log_tail = "\n".join((view.get("stdout") or "").splitlines()[-40:])
        explanation = (
            f"CI failed: {failed[0].get('name') or failed[0].get('displayTitle')} "
            f"on {failed[0].get('headBranch')} — {failed[0].get('url')}\n"
            f"Failed log tail:\n{log_tail or '(no log; open the run URL)'}"
        )
    elif in_progress:
        explanation = f"CI in progress: {in_progress[0].get('name')} ({in_progress[0].get('url')})"
    elif items:
        explanation = f"Latest CI: {items[0].get('name')} → {items[0].get('conclusion') or items[0].get('status')}"
    else:
        explanation = "No recent workflow runs found."
    return {
        "ok": True,
        "runs": items,
        "failed": failed,
        "explanation": explanation,
        "repo": str(cwd),
    }
