"""Git / GitHub helpers via git CLI (does not modify FastIntent or other cores)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from neuron.developer.index import resolve_root


def _run(args: list[str], cwd: Path, timeout: float = 20.0) -> tuple[int, str, str]:
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
        return 127, "", "git not found"
    except subprocess.TimeoutExpired:
        return 124, "", "git timeout"


def git_status(root: str | None = None) -> dict[str, Any]:
    cwd = resolve_root(root)
    code, out, err = _run(["git", "status", "--short", "--branch"], cwd)
    return {"ok": code == 0, "root": str(cwd), "stdout": out.strip(), "stderr": err.strip(), "code": code}


def git_log(root: str | None = None, *, n: int = 5) -> dict[str, Any]:
    cwd = resolve_root(root)
    code, out, err = _run(["git", "log", f"-{max(1, min(n, 20))}", "--oneline", "--decorate"], cwd)
    return {"ok": code == 0, "root": str(cwd), "commits": out.strip().splitlines(), "stderr": err.strip()}


def git_diff(root: str | None = None, *, staged: bool = False) -> dict[str, Any]:
    cwd = resolve_root(root)
    args = ["git", "diff", "--stat"] + (["--cached"] if staged else [])
    code, out, err = _run(args, cwd)
    return {"ok": code == 0, "root": str(cwd), "diff_stat": out.strip(), "stderr": err.strip()}


def git_show_latest(root: str | None = None) -> dict[str, Any]:
    cwd = resolve_root(root)
    code, out, err = _run(["git", "show", "-s", "--format=%H%n%s%n%an%n%ci", "HEAD"], cwd)
    lines = out.strip().splitlines()
    review = {
        "ok": code == 0,
        "root": str(cwd),
        "hash": lines[0] if lines else "",
        "subject": lines[1] if len(lines) > 1 else "",
        "author": lines[2] if len(lines) > 2 else "",
        "date": lines[3] if len(lines) > 3 else "",
        "stderr": err.strip(),
    }
    code2, stat, _ = _run(["git", "show", "--stat", "--oneline", "-1", "HEAD"], cwd)
    review["stat"] = stat.strip() if code2 == 0 else ""
    return review


def github_remote(root: str | None = None) -> dict[str, Any]:
    cwd = resolve_root(root)
    code, out, err = _run(["git", "remote", "-v"], cwd)
    urls = []
    for line in out.splitlines():
        m = re.search(r"(https://github\.com/[^\s]+|git@github\.com:[^\s]+)", line)
        if m:
            urls.append(m.group(1).rstrip(".git"))
    return {"ok": code == 0, "remotes": out.strip(), "github_urls": list(dict.fromkeys(urls)), "stderr": err.strip()}
