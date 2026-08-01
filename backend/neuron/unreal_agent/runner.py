"""Locate Unreal Engine / projects and run Editor Python or UAT (compose-only)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def assets_root() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "unreal_agent"
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("scripts", "cpp", "blueprints", "logs", "builds", "assets"):
        (root / sub).mkdir(exist_ok=True)
    return root


def _cfg() -> dict[str, Any]:
    try:
        return json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        ).get("unreal_agent") or {}
    except Exception:
        return {}


def find_engine() -> str | None:
    custom = str(_cfg().get("engine_path") or "").strip()
    if custom and Path(custom).is_dir():
        return custom
    # Epic Launcher default installs
    bases = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Epic Games",
        Path(r"C:\Program Files\Epic Games"),
        Path(r"D:\Program Files\Epic Games"),
        Path(r"E:\UE"),
    ]
    found: list[Path] = []
    for base in bases:
        if not base.is_dir():
            continue
        for child in base.glob("UE_*"):
            if (child / "Engine" / "Binaries" / "Win64").is_dir():
                found.append(child)
        for child in base.glob("UE*"):
            if child.is_dir() and (child / "Engine").is_dir():
                found.append(child)
    if found:
        found = sorted(found, key=lambda p: p.name, reverse=True)
        return str(found[0])
    # Environment
    for key in ("UE_ROOT", "UE4_ROOT", "UE5_ROOT"):
        val = os.environ.get(key)
        if val and Path(val).is_dir():
            return val
    return None


def find_editor_cmd(engine: str | None = None) -> str | None:
    eng = Path(engine or find_engine() or "")
    if not eng.is_dir():
        return None
    for name in ("UnrealEditor-Cmd.exe", "UE4Editor-Cmd.exe"):
        p = eng / "Engine" / "Binaries" / "Win64" / name
        if p.is_file():
            return str(p)
    which = shutil.which("UnrealEditor-Cmd")
    return which


def find_uat(engine: str | None = None) -> str | None:
    eng = Path(engine or find_engine() or "")
    if not eng.is_dir():
        return None
    for name in ("RunUAT.bat", "RunUAT.sh"):
        p = eng / "Engine" / "Build" / "BatchFiles" / name
        if p.is_file():
            return str(p)
    return None


def find_uproject(start: str | None = None) -> str | None:
    custom = str(_cfg().get("project_path") or "").strip()
    if custom and Path(custom).is_file():
        return custom
    roots = []
    if start:
        roots.append(Path(start))
    roots.append(Path.cwd())
    roots.append(Path(__file__).resolve().parents[3])  # repo-ish
    for root in roots:
        if not root.is_dir():
            continue
        hits = list(root.rglob("*.uproject"))
        # Prefer shallow
        hits = sorted(hits, key=lambda p: len(p.parts))
        if hits:
            return str(hits[0])
    return None


def write_text(rel: str, content: str) -> Path:
    path = assets_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run_editor_python(
    script_path: Path | str,
    *,
    uproject: str | None = None,
    dry_run: bool = False,
    timeout: float = 300.0,
) -> dict[str, Any]:
    script_path = Path(script_path)
    editor = find_editor_cmd()
    project = uproject or find_uproject()
    if dry_run or not editor:
        return {
            "ok": True if dry_run or script_path.is_file() else False,
            "dry_run": True,
            "editor": editor,
            "project": project,
            "script": str(script_path),
            "stderr": "" if editor else "UnrealEditor-Cmd not found — script saved.",
            "code": 0,
        }
    cmd = [editor]
    if project:
        cmd.append(project)
    cmd.extend(["-unattended", "-nop4", "-ExecutePythonScript=" + str(script_path)])
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "ok": p.returncode == 0,
            "dry_run": False,
            "editor": editor,
            "project": project,
            "script": str(script_path),
            "stdout": (p.stdout or "")[-4000:],
            "stderr": (p.stderr or "")[-2000:],
            "code": p.returncode,
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "dry_run": False, "editor": editor, "script": str(script_path), "stderr": "timeout", "code": 124}
    except Exception as exc:
        return {"ok": False, "dry_run": False, "stderr": str(exc), "code": -1}


def run_uat(args: list[str], *, dry_run: bool = False, timeout: float = 600.0) -> dict[str, Any]:
    uat = find_uat()
    if dry_run or not uat:
        return {
            "ok": True if dry_run else False,
            "dry_run": True,
            "uat": uat,
            "args": args,
            "stderr": "" if uat else "RunUAT not found",
            "code": 0 if dry_run else 127,
        }
    cmd = [uat, *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return {
            "ok": p.returncode == 0,
            "dry_run": False,
            "uat": uat,
            "args": args,
            "stdout": (p.stdout or "")[-5000:],
            "stderr": (p.stderr or "")[-2000:],
            "code": p.returncode,
            "cmd": cmd,
        }
    except Exception as exc:
        return {"ok": False, "dry_run": False, "stderr": str(exc), "code": -1}


def open_unreal() -> Any:
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        # Prefer opening .uproject via start, else Unreal Editor app
        project = find_uproject()
        if project:
            os.startfile(project)  # type: ignore[attr-defined]
            return {"ok": True, "project": project}
        return tool_registry.execute("open_app", {"name": "UnrealEditor"}, confirmed=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
