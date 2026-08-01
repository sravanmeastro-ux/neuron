"""Deep project indexer — folders, source, deps, assets, build, docs."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from neuron.developer.index import resolve_root

_CACHE: dict[str, dict[str, Any]] = {}

_SKIP_DEEP = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".idea", ".vs", ".cursor", "coverage", ".mypy_cache", ".pytest_cache",
    "eggs", "*.egg-info",
}

_BUILD_DIR_NAMES = {
    "dist", "build", "out", ".next", "target", "bin", "obj", "Release", "Debug",
    "cmake-build-debug", "cmake-build-release", "_build",
}

_ASSET_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".mp3", ".wav", ".ogg", ".mp4", ".webm", ".mov",
    ".ttf", ".otf", ".woff", ".woff2",
    ".fbx", ".obj", ".gltf", ".glb", ".blend", ".uasset", ".umap",
    ".psd", ".ai", ".hdr", ".exr",
}

_SOURCE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".rs", ".go", ".java", ".kt", ".cs", ".cpp", ".cc", ".cxx", ".h", ".hpp",
    ".c", ".rb", ".php", ".swift", ".m", ".mm", ".scala", ".lua", ".r",
    ".vue", ".svelte", ".sql", ".sh", ".ps1", ".bat",
}

_DOC_EXT = {".md", ".rst", ".txt", ".adoc"}
_DOC_NAMES = {"readme", "changelog", "contributing", "license", "authors"}

_MANIFEST_READERS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
    "pom.xml",
)


def _should_skip_dir(name: str) -> bool:
    if name in _SKIP_DEEP or name.endswith(".egg-info"):
        return True
    return False


def deep_index(root: str | Path | None = None, *, max_files: int = 8000, force: bool = False) -> dict[str, Any]:
    root_p = resolve_root(str(root) if root else None)
    cache_key = f"{root_p}:{max_files}"
    if not force and cache_key in _CACHE:
        return _CACHE[cache_key]
    folders: list[str] = []
    sources: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    build_outputs: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    other_count = 0
    lang_counts: Counter[str] = Counter()
    top_folders: list[str] = []

    try:
        top_folders = sorted(
            [p.name for p in root_p.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=str.lower,
        )[:40]
    except OSError:
        pass

    file_count = 0
    build_dirs_seen: set[str] = set()

    for dirpath, dirnames, filenames in _walk(root_p):
        rel_dir = dirpath.relative_to(root_p).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        # prune
        pruned = []
        for d in list(dirnames):
            if _should_skip_dir(d):
                continue
            if d in _BUILD_DIR_NAMES or any(part in _BUILD_DIR_NAMES for part in Path(rel_dir, d).parts):
                # still enter build dirs but mark lightly
                pass
            pruned.append(d)
        dirnames[:] = pruned

        if rel_dir and len(folders) < 500:
            depth = rel_dir.count("/") + 1
            if depth <= 3:
                folders.append(rel_dir)

        # detect build dir membership
        parts = set(Path(rel_dir).parts) if rel_dir else set()
        in_build = bool(parts & _BUILD_DIR_NAMES)

        for name in filenames:
            if file_count >= max_files:
                break
            file_count += 1
            path = dirpath / name
            rel = path.relative_to(root_p).as_posix()
            suf = path.suffix.lower()
            stem = path.stem.lower()

            if in_build or (path.parent.name in _BUILD_DIR_NAMES):
                build_dirs_seen.add(str(Path(*[p for p in Path(rel).parts if p in _BUILD_DIR_NAMES][:1]) or path.parent.name))
                if len(build_outputs) < 200:
                    build_outputs.append({"path": rel, "ext": suf, "size": _size(path)})
                continue

            if suf in _ASSET_EXT:
                if len(assets) < 400:
                    assets.append({"path": rel, "ext": suf, "size": _size(path)})
                continue

            if suf in _DOC_EXT or stem in _DOC_NAMES:
                if len(docs) < 200:
                    docs.append({"path": rel, "ext": suf, "size": _size(path)})
                continue

            if suf in _SOURCE_EXT:
                lang = _lang_for(suf)
                lang_counts[lang] += 1
                if len(sources) < 3000:
                    sources.append({"path": rel, "lang": lang, "ext": suf, "size": _size(path)})
                continue

            other_count += 1

        if file_count >= max_files:
            break

    deps = _read_dependencies(root_p)
    modules = _infer_modules(root_p, sources)
    summary = {
        "root": str(root_p),
        "name": root_p.name,
        "top_folders": top_folders,
        "folder_count": len(folders),
        "folders_sample": folders[:80],
        "source_count": len(sources),
        "sources_sample": sources[:60],
        "languages": dict(lang_counts.most_common(20)),
        "dependency_manifests": deps.get("manifests") or [],
        "dependencies": deps.get("packages") or {},
        "asset_count": len(assets),
        "assets_sample": assets[:40],
        "build_dir_count": len(build_dirs_seen),
        "build_dirs": sorted(build_dirs_seen),
        "build_outputs_sample": build_outputs[:40],
        "doc_count": len(docs),
        "docs": docs[:40],
        "modules": modules,
        "file_count_scanned": file_count,
        "other_files": other_count,
        "readme": _readme_excerpt(root_p, docs),
    }
    _CACHE[cache_key] = summary
    return summary


def clear_index_cache() -> None:
    _CACHE.clear()


def _walk(root: Path):
    yield from os_walk_safe(root)


def os_walk_safe(root: Path):
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        yield Path(dirpath), dirnames, filenames


def _size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _lang_for(suf: str) -> str:
    return {
        ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
        ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
        ".rs": "rust", ".go": "go", ".java": "java", ".kt": "kotlin", ".cs": "csharp",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "c_header", ".hpp": "cpp",
        ".c": "c", ".rb": "ruby", ".php": "php", ".swift": "swift", ".vue": "vue",
        ".svelte": "svelte", ".sql": "sql", ".sh": "shell", ".ps1": "powershell",
    }.get(suf, suf.lstrip(".") or "unknown")


def _read_dependencies(root: Path) -> dict[str, Any]:
    manifests: list[str] = []
    packages: dict[str, list[str]] = defaultdict(list)

    pkg = root / "package.json"
    if pkg.is_file():
        manifests.append("package.json")
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                for name in (data.get(section) or {}):
                    packages["npm"].append(name)
        except Exception:
            pass

    req = root / "requirements.txt"
    if req.is_file():
        manifests.append("requirements.txt")
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip()
            if name:
                packages["pip"].append(name)

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        manifests.append("pyproject.toml")
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'^\s*"([A-Za-z0-9_.\-]+)"\s*[>=<]', text, re.M):
            packages["pip"].append(m.group(1))
        for m in re.finditer(r'^\s*([A-Za-z0-9_.\-]+)\s*=\s*"', text, re.M):
            if m.group(1) not in ("name", "version", "description", "readme", "requires-python"):
                packages["pip"].append(m.group(1))

    cargo = root / "Cargo.toml"
    if cargo.is_file():
        manifests.append("Cargo.toml")
        in_deps = False
        for line in cargo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("[") and "dependencies" in line:
                in_deps = True
                continue
            if line.strip().startswith("["):
                in_deps = False
            if in_deps:
                m = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*=", line)
                if m:
                    packages["cargo"].append(m.group(1))

    gomod = root / "go.mod"
    if gomod.is_file():
        manifests.append("go.mod")
        for line in gomod.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*([^\s]+)\s+v[\d.]", line)
            if m and not m.group(1).startswith("module"):
                packages["go"].append(m.group(1))

    # dedupe
    packages = {k: sorted(set(v))[:200] for k, v in packages.items()}
    return {"manifests": manifests, "packages": packages}


def _infer_modules(root: Path, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Top-level packages / feature areas from source path prefixes."""
    buckets: Counter[str] = Counter()
    for s in sources:
        parts = Path(s["path"]).parts
        if not parts:
            continue
        if parts[0] in ("src", "lib", "app", "apps", "packages", "backend", "frontend", "server", "client"):
            key = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        else:
            key = parts[0]
        buckets[key] += 1
    return [{"module": m, "files": n} for m, n in buckets.most_common(40)]


def _readme_excerpt(root: Path, docs: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [root / "README.md", root / "readme.md", root / "README.rst"]
    for d in docs:
        if Path(d["path"]).name.lower().startswith("readme"):
            candidates.append(root / d["path"])
    for c in candidates:
        if c.is_file():
            text = c.read_text(encoding="utf-8", errors="replace")
            # first meaningful paragraph
            lines = [ln.strip() for ln in text.splitlines()]
            title = next((ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")), root.name)
            paras = []
            buf = []
            for ln in lines:
                if ln.startswith("#"):
                    continue
                if not ln:
                    if buf:
                        paras.append(" ".join(buf))
                        buf = []
                    if paras:
                        break
                    continue
                buf.append(ln)
            if buf and not paras:
                paras.append(" ".join(buf))
            return {"path": str(c.relative_to(root)), "title": title, "summary": (paras[0] if paras else "")[:600]}
    return {"path": "", "title": root.name, "summary": ""}
