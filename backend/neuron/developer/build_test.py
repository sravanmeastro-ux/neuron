"""Build / test monitoring — detect commands from project manifests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from neuron.developer.index import index_project, resolve_root


def detect_build_commands(root: str | None = None) -> dict[str, Any]:
    root_p = resolve_root(root)
    idx = index_project(root_p)
    cmds: list[dict[str, str]] = []

    pkg = root_p / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {})
            for name in ("build", "compile", "dev", "start"):
                if name in scripts:
                    cmds.append({"name": name, "cmd": f"npm run {name}", "ecosystem": "node"})
        except Exception:
            pass
        if not any(c["name"] == "build" for c in cmds):
            cmds.append({"name": "build", "cmd": "npm run build", "ecosystem": "node"})

    if (root_p / "pyproject.toml").is_file() or (root_p / "setup.py").is_file():
        cmds.append({"name": "build", "cmd": "python -m build", "ecosystem": "python"})
    if (root_p / "Cargo.toml").is_file():
        cmds.append({"name": "build", "cmd": "cargo build", "ecosystem": "rust"})
    if (root_p / "CMakeLists.txt").is_file():
        cmds.append({"name": "build", "cmd": "cmake --build build", "ecosystem": "cpp"})
    if list(root_p.glob("*.sln")):
        cmds.append({"name": "build", "cmd": "dotnet build", "ecosystem": "dotnet"})
    if (root_p / "pom.xml").is_file():
        cmds.append({"name": "build", "cmd": "mvn -q package", "ecosystem": "java"})
    if (root_p / "Dockerfile").is_file():
        cmds.append({"name": "docker_build", "cmd": f"docker build -t {idx.name.lower()}:dev .", "ecosystem": "docker"})

    return {"ok": True, "root": str(root_p), "commands": cmds, "languages": idx.languages}


def detect_test_commands(root: str | None = None) -> dict[str, Any]:
    root_p = resolve_root(root)
    idx = index_project(root_p)
    cmds: list[dict[str, str]] = []
    pkg = root_p / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {})
            if "test" in scripts:
                cmds.append({"name": "test", "cmd": "npm test", "ecosystem": "node"})
        except Exception:
            cmds.append({"name": "test", "cmd": "npm test", "ecosystem": "node"})
    if "python" in idx.languages:
        cmds.append({"name": "pytest", "cmd": "pytest -q", "ecosystem": "python"})
        cmds.append({"name": "unittest", "cmd": "python -m unittest", "ecosystem": "python"})
    if (root_p / "Cargo.toml").is_file():
        cmds.append({"name": "test", "cmd": "cargo test", "ecosystem": "rust"})
    if list(root_p.glob("*.sln")) or "csharp" in idx.languages:
        cmds.append({"name": "test", "cmd": "dotnet test", "ecosystem": "dotnet"})
    if (root_p / "pom.xml").is_file():
        cmds.append({"name": "test", "cmd": "mvn -q test", "ecosystem": "java"})
    return {"ok": True, "root": str(root_p), "commands": cmds, "has_tests": idx.has_tests}


def run_monitored(cmd: str, root: str | None = None, *, timeout: float = 120.0) -> dict[str, Any]:
    """Run a build/test command and capture exit + tail output (developer monitoring)."""
    cwd = resolve_root(root)
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        out = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        tail = "\n".join(out.splitlines()[-40:])
        return {
            "ok": p.returncode == 0,
            "code": p.returncode,
            "cmd": cmd,
            "root": str(cwd),
            "tail": tail,
            "passed": p.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": 124, "cmd": cmd, "root": str(cwd), "tail": "timeout", "passed": False}
    except Exception as exc:
        return {"ok": False, "code": -1, "cmd": cmd, "root": str(cwd), "tail": str(exc), "passed": False}
