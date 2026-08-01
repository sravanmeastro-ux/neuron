"""Locate Blender executable and run bpy scripts via CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def assets_root() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "blender_agent"
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    (root / "imports").mkdir(exist_ok=True)
    (root / "renders").mkdir(exist_ok=True)
    (root / "assets").mkdir(exist_ok=True)
    return root


def _cfg_blender_path() -> str:
    try:
        cfg = json.loads(
            (Path(__file__).resolve().parents[2] / "config.json").read_text(encoding="utf-8")
        )
        return str(((cfg.get("blender_agent") or {}).get("blender_path") or "")).strip()
    except Exception:
        return ""


def find_blender() -> str | None:
    """Return path to blender executable if available."""
    custom = _cfg_blender_path()
    if custom and Path(custom).is_file():
        return custom
    which = shutil.which("blender")
    if which:
        return which
    # Common Windows install locations
    candidates = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for base in (pf, pf86):
        bdir = Path(base) / "Blender Foundation"
        if bdir.is_dir():
            for child in sorted(bdir.glob("Blender *"), reverse=True):
                exe = child / "blender.exe"
                if exe.is_file():
                    candidates.append(str(exe))
    # Steam
    steam = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam" / "steamapps" / "common" / "Blender"
    if (steam / "blender.exe").is_file():
        candidates.append(str(steam / "blender.exe"))
    return candidates[0] if candidates else None


def write_script(name: str, source: str) -> Path:
    path = assets_root() / "scripts" / f"{name}_{int(time.time()) % 100000}.py"
    path.write_text(source, encoding="utf-8")
    return path


def run_script(
    script_path: Path | str,
    *,
    blend_file: str | None = None,
    background: bool = True,
    timeout: float = 180.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a bpy script with Blender CLI."""
    script_path = Path(script_path)
    blender = find_blender()
    if dry_run or not blender:
        return {
            "ok": True if dry_run or script_path.is_file() else False,
            "dry_run": True,
            "blender": blender,
            "script": str(script_path),
            "stdout": "",
            "stderr": "" if blender else "Blender executable not found — script saved for later.",
            "code": 0 if dry_run else (0 if blender else 127),
        }
    cmd = [blender]
    if blend_file:
        cmd.append(blend_file)
    if background:
        cmd.append("--background")
    cmd.extend(["--python", str(script_path)])
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
            "blender": blender,
            "script": str(script_path),
            "stdout": (p.stdout or "")[-4000:],
            "stderr": (p.stderr or "")[-2000:],
            "code": p.returncode,
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "dry_run": False, "blender": blender, "script": str(script_path), "stderr": "timeout", "code": 124}
    except Exception as exc:
        return {"ok": False, "dry_run": False, "blender": blender, "script": str(script_path), "stderr": str(exc), "code": -1}


def open_blender_app() -> Any:
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        if tool_registry.get("blender.open") or tool_registry.get("blender_open"):
            t = "blender.open" if tool_registry.get("blender.open") else "blender_open"
            return tool_registry.execute(t, {}, confirmed=True)
        return tool_registry.execute("open_app", {"name": "Blender"}, confirmed=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
