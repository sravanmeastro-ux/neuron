"""Files skill workflows."""

from __future__ import annotations

from neuron.skills._util import arg, as_result, handler
from neuron.windows.result import ToolResult, fail


def find(query: str, root: str = "", limit: int = 25) -> ToolResult:
    """Search common user folders for a filename / pattern."""
    q = (query or "").strip()
    if not q:
        return fail("Need a file search query.")
    try:
        from neuron.tools import files_tools
        return as_result(
            files_tools.search_files({"query": q, "root": root or "", "limit": int(limit)}),
            method="files",
        )
    except Exception as exc:
        return fail(str(exc))


def open(path: str = "", query: str = "") -> ToolResult:
    """Open a file by path, or find+open the first match for query."""
    p = (path or "").strip()
    q = (query or "").strip()
    if not p and q:
        hit = find(q, limit=5)
        if not hit.success:
            return hit
        paths = (
            (hit.state or {}).get("hits")
            or (hit.state or {}).get("paths")
            or (hit.state or {}).get("results")
            or []
        )
        if isinstance(paths, list) and paths:
            first = paths[0]
            p = first.get("path") if isinstance(first, dict) else str(first)
        if not p:
            return fail(f"Found matches but no path to open: {hit.message}")
    if not p:
        return fail("Need a file path or search query.")
    try:
        from neuron.tools import files_tools
        return as_result(files_tools.open_file({"path": p}), method="files")
    except Exception as exc:
        return fail(str(exc))


def open_folder(location: str) -> ToolResult:
    loc = (location or "").strip()
    if not loc:
        return fail("Need a folder name or path.")
    try:
        from neuron.tools import files_tools
        return as_result(files_tools.open_folder({"location": loc}), method="files")
    except Exception as exc:
        return fail(str(exc))


find_tool = handler(lambda a: find(str(arg(a, "query", "name", "pattern")), str(arg(a, "root", "in", "location", default="")), int(arg(a, "limit", default=25) or 25)))
open_tool = handler(lambda a: open(str(arg(a, "path", "file", default="")), str(arg(a, "query", "name", default=""))))
open_folder_tool = handler(lambda a: open_folder(str(arg(a, "location", "path", "folder", "name"))))
