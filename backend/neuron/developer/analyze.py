"""Code analysis + compiler/stack-trace diagnostics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from neuron.developer.index import index_project, resolve_root


def analyze_project(root: str | None = None) -> dict[str, Any]:
    idx = index_project(root)
    summary = (
        f"Project '{idx.name}' at {idx.root}: "
        f"languages={', '.join(idx.languages) or 'unknown'}; "
        f"frameworks={', '.join(idx.frameworks) or 'none'}; "
        f"git={'yes' if idx.has_git else 'no'}; "
        f"docker={'yes' if idx.has_docker else 'no'}; "
        f"tests={'detected' if idx.has_tests else 'not obvious'}; "
        f"~{idx.file_count} files."
    )
    return {"ok": True, "index": idx.to_dict(), "summary": summary}


def parse_diagnostics(text: str) -> dict[str, Any]:
    """Parse common compiler / runtime diagnostics from pasted text."""
    raw = text or ""
    findings: list[dict[str, Any]] = []

    # Python traceback
    for m in re.finditer(
        r'File "([^"]+)", line (\d+), in ([^\n]+)\n\s*(.*)',
        raw,
    ):
        findings.append({
            "kind": "python_traceback",
            "file": m.group(1),
            "line": int(m.group(2)),
            "func": m.group(3).strip(),
            "code": m.group(4).strip(),
        })
    m = re.search(r"^(\w+Error):\s*(.+)$", raw, re.M)
    if m:
        findings.append({"kind": "python_error", "type": m.group(1), "message": m.group(2).strip()})

    # TypeScript / ESLint style
    for m in re.finditer(r"([^\s(:]+)\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*(.+)", raw):
        findings.append({
            "kind": "tsc",
            "file": m.group(1),
            "line": int(m.group(2)),
            "col": int(m.group(3)),
            "code": m.group(4),
            "message": m.group(5).strip(),
        })
    for m in re.finditer(r"([^\s:]+):(\d+):(\d+):\s*(error|warning):\s*(.+)", raw):
        findings.append({
            "kind": "generic_diag",
            "file": m.group(1),
            "line": int(m.group(2)),
            "col": int(m.group(3)),
            "severity": m.group(4),
            "message": m.group(5).strip(),
        })

    # Rust
    for m in re.finditer(r"-->\s+([^:]+):(\d+):(\d+)", raw):
        findings.append({"kind": "rust", "file": m.group(1), "line": int(m.group(2)), "col": int(m.group(3))})
    if "error[E" in raw:
        for m in re.finditer(r"error\[(E\d+)\]:\s*(.+)", raw):
            findings.append({"kind": "rust_error", "code": m.group(1), "message": m.group(2).strip()})

    # C++ / clang / MSVC
    for m in re.finditer(r"([^\s(]+)\((\d+)\):\s*error\s+(C\d+):\s*(.+)", raw):
        findings.append({
            "kind": "msvc",
            "file": m.group(1),
            "line": int(m.group(2)),
            "code": m.group(3),
            "message": m.group(4).strip(),
        })

    # Java
    for m in re.finditer(r"([^\s:]+):(\d+):\s*error:\s*(.+)", raw):
        if m.group(1).endswith(".java"):
            findings.append({
                "kind": "javac",
                "file": m.group(1),
                "line": int(m.group(2)),
                "message": m.group(3).strip(),
            })

    return {
        "ok": True,
        "count": len(findings),
        "findings": findings[:50],
        "primary": findings[0] if findings else None,
    }


def localize_bug(text: str, root: str | None = None) -> dict[str, Any]:
    """Heuristic bug localization from stack traces / error text."""
    diag = parse_diagnostics(text)
    root_p = resolve_root(root)
    suspects: list[dict[str, Any]] = []
    for f in diag.get("findings") or []:
        fp = f.get("file") or ""
        line = f.get("line")
        score = 0.5
        if f.get("kind") in ("python_error", "tsc", "rust_error", "msvc", "javac"):
            score = 0.9
        if f.get("kind") == "python_traceback":
            score = 0.75
        # Prefer project-local files
        local = False
        try:
            p = Path(fp)
            if not p.is_absolute():
                p = root_p / fp
            local = p.exists() and str(root_p) in str(p.resolve())
        except Exception:
            pass
        if local:
            score += 0.1
        suspects.append({
            "file": fp,
            "line": line,
            "score": round(min(score, 1.0), 2),
            "reason": f.get("message") or f.get("kind") or "diagnostic",
            "kind": f.get("kind"),
        })
    suspects.sort(key=lambda x: -x["score"])
    return {
        "ok": True,
        "suspects": suspects[:10],
        "diagnostics": diag,
        "advice": (
            f"Start at {suspects[0]['file']}:{suspects[0].get('line')}"
            if suspects else "No clear localization — paste the full stack trace or compiler output."
        ),
    }


def explain_code_or_trace(text: str) -> dict[str, Any]:
    """Structured explanation of stack traces / errors / short snippets."""
    diag = parse_diagnostics(text)
    if diag["count"]:
        primary = diag["primary"] or {}
        kind = primary.get("kind", "error")
        lines = [
            f"This looks like a {kind.replace('_', ' ')}.",
        ]
        if primary.get("file"):
            lines.append(f"Focus: {primary.get('file')}" + (f":{primary['line']}" if primary.get("line") else ""))
        if primary.get("message"):
            lines.append(f"Message: {primary['message']}")
        if primary.get("type"):
            lines.append(f"Exception: {primary['type']}")
        lines.append("Suggested next step: open the cited file, inspect the failing line, then re-run the failing test/build.")
        return {"ok": True, "explanation": " ".join(lines), "diagnostics": diag}

    # Generic code snippet explanation heuristics
    snippet = (text or "").strip()
    hints = []
    if "useState" in snippet or "useEffect" in snippet or "React" in snippet:
        hints.append("React component / hooks usage")
    if "async def" in snippet or "await " in snippet:
        hints.append("async control flow")
    if "fn main" in snippet or "let mut" in snippet:
        hints.append("Rust ownership / entrypoint")
    if "public static void main" in snippet:
        hints.append("Java entrypoint")
    if "#include" in snippet:
        hints.append("C/C++ translation unit")
    if not hints:
        hints.append("general code snippet")
    return {
        "ok": True,
        "explanation": f"Snippet appears to involve: {', '.join(hints)}. Share a specific question or error for a deeper pass.",
        "hints": hints,
    }
