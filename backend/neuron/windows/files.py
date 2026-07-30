"""Phase 2 file / folder tools — shell + Explorer, no paid APIs."""

from __future__ import annotations

import os
from pathlib import Path

from neuron.windows.result import ToolResult, fail, ok


def _log(msg: str) -> None:
    print(f"[win-files] {msg}", flush=True)


def open_file(args: dict | None = None) -> ToolResult:
    args = args or {}
    path = (args.get("path") or args.get("file") or args.get("name") or "").strip()
    if not path:
        return fail("Need a file path.")
    # Expand ~ and env vars
    path = os.path.expandvars(os.path.expanduser(path))
    p = Path(path)
    if not p.is_file():
        # Try Desktop / Documents
        for base in (
            Path.home() / "Desktop",
            Path.home() / "Documents",
            Path.home() / "Downloads",
        ):
            cand = base / path
            if cand.is_file():
                p = cand
                break
    if not p.is_file():
        return fail(f"File not found: {path}", state={"path": path})
    try:
        os.startfile(str(p))  # noqa: S606 — intentional Windows open
        return ok(f"Opened {p.name}.", state={"path": str(p)}, method="shell")
    except Exception as exc:
        return fail(f"Couldn't open file: {exc}", state={"path": str(p)})


def open_folder(args: dict | None = None) -> ToolResult:
    args = args or {}
    location = (
        args.get("location")
        or args.get("path")
        or args.get("folder")
        or args.get("name")
        or ""
    ).strip()
    if not location:
        return fail("Need a folder name or path.")

    # Absolute / expanded path first
    expanded = os.path.expandvars(os.path.expanduser(location))
    if os.path.isdir(expanded):
        try:
            os.startfile(expanded)
            return ok(f"Opening {expanded}.", state={"path": expanded}, method="shell")
        except Exception as exc:
            return fail(str(exc), state={"path": expanded})

    try:
        import actions
        msg = actions.open_folder(location)
        # actions returns spoken string; treat "couldn't" as failure
        low = (msg or "").lower()
        if "couldn't" in low or "could not" in low:
            return fail(msg, state={"location": location}, method="shell")
        return ok(msg, state={"location": location}, method="shell")
    except Exception as exc:
        return fail(str(exc), state={"location": location})


def search_files(args: dict | None = None) -> ToolResult:
    """Local filename search under common user folders (no cloud APIs)."""
    args = args or {}
    query = (args.get("query") or args.get("name") or args.get("pattern") or "").strip()
    if not query:
        return fail("Need a search query.")
    root = (args.get("root") or args.get("in") or args.get("location") or "").strip()
    limit = int(args.get("limit") or 25)

    roots: list[Path] = []
    if root:
        rp = Path(os.path.expandvars(os.path.expanduser(root)))
        if rp.is_dir():
            roots.append(rp)
    if not roots:
        home = Path.home()
        for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"):
            p = home / name
            if p.is_dir():
                roots.append(p)

    needle = query.lower()
    # Support simple *.ext patterns
    ext = ""
    if needle.startswith("*.") and " " not in needle:
        ext = needle[1:]  # .pdf
        needle = ""

    hits: list[str] = []
    try:
        for base in roots:
            for dirpath, dirnames, filenames in os.walk(base):
                # Skip heavy / hidden trees
                dirnames[:] = [
                    d for d in dirnames
                    if not d.startswith(".") and d.lower() not in (
                        "node_modules", "appdata", ".git", "__pycache__",
                    )
                ]
                for fn in filenames:
                    low = fn.lower()
                    if ext and not low.endswith(ext):
                        continue
                    if needle and needle not in low:
                        continue
                    hits.append(str(Path(dirpath) / fn))
                    if len(hits) >= limit:
                        break
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
    except Exception as exc:
        return fail(f"Search failed: {exc}", state={"query": query})

    if not hits:
        return ok(
            f"No files matching '{query}'.",
            state={"query": query, "hits": [], "roots": [str(r) for r in roots]},
            method="filesystem",
        )
    preview = "; ".join(Path(h).name for h in hits[:8])
    return ok(
        f"Found {len(hits)} file(s): {preview}",
        state={"query": query, "hits": hits, "roots": [str(r) for r in roots]},
        method="filesystem",
    )
