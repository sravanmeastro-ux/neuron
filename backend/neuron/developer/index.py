"""Workspace resolution + project indexing (read-only filesystem)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from neuron.developer.types import ProjectIndex

_CACHE: dict[str, ProjectIndex] = {}

_MANIFESTS = {
    "package.json": ("javascript", "node"),
    "package-lock.json": ("javascript", "npm"),
    "yarn.lock": ("javascript", "yarn"),
    "pnpm-lock.yaml": ("javascript", "pnpm"),
    "pyproject.toml": ("python", "pip"),
    "requirements.txt": ("python", "pip"),
    "Pipfile": ("python", "pipenv"),
    "Cargo.toml": ("rust", "cargo"),
    "CMakeLists.txt": ("cpp", "cmake"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("java", "gradle"),
    "go.mod": ("go", "go"),
    "Gemfile": ("ruby", "bundler"),
    "composer.json": ("php", "composer"),
    "Dockerfile": ("docker", "docker"),
    "docker-compose.yml": ("docker", "docker"),
    "docker-compose.yaml": ("docker", "docker"),
    ".sln": ("csharp", "msbuild"),
}

_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "out", ".next", "target",
    "__pycache__", ".venv", "venv", ".tox", "coverage", ".idea", ".vs",
}


def default_workspace() -> Path:
    """Prefer cwd, then parent of backend (repo root), then user home projects."""
    cwd = Path.cwd()
    if _looks_like_project(cwd):
        return cwd
    # backend/ → repo root
    here = Path(__file__).resolve()
    for p in [here.parents[2], here.parents[3] if len(here.parents) > 3 else None]:
        if p and _looks_like_project(p):
            return p
    # Workspace often "c:\fillo jarvis"
    jarvis = Path(r"c:\fillo jarvis")
    if jarvis.is_dir():
        return jarvis
    return cwd


def _looks_like_project(path: Path) -> bool:
    if not path.is_dir():
        return False
    markers = list(_MANIFESTS.keys()) + [".git", "src", "backend", "app"]
    return any((path / m).exists() for m in markers)


def resolve_root(path: str | None = None) -> Path:
    if path:
        p = Path(path).expanduser().resolve()
        if p.is_file():
            return p.parent
        return p
    return default_workspace().resolve()


def index_project(root: str | Path | None = None, *, max_files: int = 4000) -> ProjectIndex:
    root_p = resolve_root(str(root) if root else None)
    key = str(root_p)
    if key in _CACHE:
        return _CACHE[key]

    languages: set[str] = set()
    frameworks: set[str] = set()
    managers: set[str] = set()
    manifests: list[str] = []
    entrypoints: list[str] = []
    top_dirs: list[str] = []
    file_count = 0
    has_git = (root_p / ".git").exists()
    has_docker = False
    has_tests = False
    ide_hints: list[str] = []

    if (root_p / ".vscode").is_dir():
        ide_hints.append("vscode")
    if (root_p / ".cursor").is_dir() or any(root_p.glob("*.code-workspace")):
        ide_hints.append("cursor")
    if list(root_p.glob("*.sln")) or list(root_p.glob("*.csproj")):
        ide_hints.append("visual_studio")
        languages.add("csharp")

    try:
        top_dirs = sorted(
            [d.name for d in root_p.iterdir() if d.is_dir() and d.name not in _SKIP_DIRS]
        )[:20]
    except Exception:
        top_dirs = []

    for dirpath, dirnames, filenames in os.walk(root_p):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root_p).as_posix()
        for fn in filenames:
            file_count += 1
            if file_count > max_files:
                break
            low = fn.lower()
            path = Path(dirpath) / fn
            rel = path.relative_to(root_p).as_posix()

            if fn in _MANIFESTS or any(fn.endswith(ext) for ext in (".sln", ".csproj")):
                manifests.append(rel)
                if fn in _MANIFESTS:
                    lang, mgr = _MANIFESTS[fn]
                    languages.add(lang)
                    managers.add(mgr)
                if "docker" in low:
                    has_docker = True

            if low in ("dockerfile",) or low.startswith("docker-compose"):
                has_docker = True
                languages.add("docker")

            if "test" in low or low.startswith("spec.") or low.endswith("_test.py") or low.endswith(".test.ts") or low.endswith(".test.tsx"):
                has_tests = True

            if low in ("main.py", "app.py", "index.js", "index.ts", "main.rs", "main.cpp", "program.cs", "main.go"):
                entrypoints.append(rel)

            # language by extension
            ext_map = {
                ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
                ".jsx": "javascript", ".rs": "rust", ".cpp": "cpp", ".cc": "cpp", ".h": "cpp",
                ".hpp": "cpp", ".c": "c", ".java": "java", ".cs": "csharp", ".go": "go",
                ".rb": "ruby", ".php": "php", ".vue": "javascript", ".svelte": "javascript",
            }
            suf = Path(fn).suffix.lower()
            if suf in ext_map:
                languages.add(ext_map[suf])

            # frameworks
            if fn == "package.json":
                try:
                    pkg = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                    if "react" in deps:
                        frameworks.add("react")
                    if "electron" in deps:
                        frameworks.add("electron")
                    if "next" in deps:
                        frameworks.add("next")
                    if "vue" in deps:
                        frameworks.add("vue")
                    if "express" in deps:
                        frameworks.add("express")
                except Exception:
                    pass
            if fn == "Cargo.toml":
                frameworks.add("rust")
            if "electron" in rel_dir.lower():
                frameworks.add("electron")

        if file_count > max_files:
            break

    # Prefer cursor/vscode for this repo
    if "cursor" not in ide_hints:
        ide_hints.append("cursor")
    if "vscode" not in ide_hints:
        ide_hints.append("vscode")

    idx = ProjectIndex(
        root=str(root_p),
        name=root_p.name,
        languages=sorted(languages),
        frameworks=sorted(frameworks),
        package_managers=sorted(managers),
        manifests=manifests[:40],
        entrypoints=entrypoints[:20],
        has_git=has_git,
        has_docker=has_docker,
        has_tests=has_tests,
        ide_hints=ide_hints,
        file_count=file_count,
        top_dirs=top_dirs,
    )
    _CACHE[key] = idx
    return idx


def clear_index_cache() -> None:
    _CACHE.clear()
