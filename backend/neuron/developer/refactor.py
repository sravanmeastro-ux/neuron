"""Refactoring suggestions + scaffold recipes (suggestions only unless confirmed)."""

from __future__ import annotations

import re
from typing import Any

from neuron.developer.index import index_project


def refactor_suggestions(text: str = "", root: str | None = None) -> dict[str, Any]:
    idx = index_project(root)
    suggestions: list[str] = []
    blob = (text or "").lower()

    if "class" in blob or "refactor this class" in blob:
        suggestions += [
            "Extract interfaces for the public API of the class.",
            "Split large methods (>40 lines) into helpers with clear names.",
            "Replace inheritance with composition where coupling is high.",
            "Add unit tests around behavior before moving code.",
        ]
    if "duplicate" in blob or "dry" in blob:
        suggestions.append("Deduplicate shared logic into a utility module and import it.")
    if "async" in blob:
        suggestions.append("Ensure async functions are awaited; avoid blocking I/O on the event loop.")
    if "react" in blob or "react" in idx.frameworks:
        suggestions += [
            "Extract presentational components; keep hooks near data boundaries.",
            "Memoize expensive lists with useMemo only when profiling shows need.",
        ]
    if "electron" in idx.frameworks:
        suggestions.append("Keep Node-only APIs in the main process; expose a narrow preload bridge.")
    if not suggestions:
        suggestions = [
            "Identify the module's responsibility and shrink its public surface.",
            "Add characterization tests, then rename for clarity.",
            "Remove dead code and unused dependencies.",
            "Improve error handling at system boundaries.",
        ]
    return {
        "ok": True,
        "project": idx.name,
        "languages": idx.languages,
        "suggestions": suggestions[:12],
    }


def scaffold_plan(goal: str, root: str | None = None) -> dict[str, Any]:
    """Plan steps for creating apps (React/Electron/Python) — compose IDE + terminal later."""
    g = (goal or "").lower()
    idx = index_project(root)
    steps: list[str] = []
    if "react" in g:
        steps = [
            "Open terminal in workspace",
            "npm create vite@latest my-app -- --template react-ts",
            "cd my-app && npm install",
            "npm run dev",
            "Open the project in Cursor or VS Code",
        ]
        kind = "react"
    elif "electron" in g:
        steps = [
            "Scaffold Electron + React (or electron-vite)",
            "Install dependencies",
            "Configure main/preload/renderer",
            "Run in development mode",
        ]
        kind = "electron"
    elif "rust" in g:
        steps = ["cargo new my_app", "cd my_app", "cargo run", "Open in IDE"]
        kind = "rust"
    elif "python" in g:
        steps = ["python -m venv .venv", "Activate venv", "pip install -r requirements.txt (or poetry)", "Open in IDE"]
        kind = "python"
    else:
        steps = [
            f"Index workspace at {idx.root}",
            "Choose stack (React / Python / Rust / …)",
            "Scaffold with the ecosystem CLI",
            "Open in Cursor / VS Code",
            "Run tests / start dev server",
        ]
        kind = "generic"
    return {"ok": True, "kind": kind, "steps": steps, "ide": idx.ide_hints[:2]}


def docs_outline(root: str | None = None) -> dict[str, Any]:
    idx = index_project(root)
    sections = [
        f"# {idx.name}",
        "## Overview",
        "## Stack",
        f"- Languages: {', '.join(idx.languages) or 'TBD'}",
        f"- Frameworks: {', '.join(idx.frameworks) or 'TBD'}",
        "## Setup",
        "## Development",
        "## Testing",
        "## Architecture",
        "## Contributing",
    ]
    if idx.has_docker:
        sections.append("## Docker")
    return {"ok": True, "markdown": "\n\n".join(sections), "project": idx.to_dict()}
