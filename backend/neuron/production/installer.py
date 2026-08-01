"""Professional installer helpers (invoked by Install-NEURON.ps1 / tools)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from neuron.production.paths import PRODUCT_NAME, PRODUCT_VERSION, install_marker_path, repo_root


def install_dependencies(*, upgrade_pip: bool = True) -> dict[str, Any]:
    root = repo_root()
    req = root / "requirements.txt"
    if not req.is_file():
        return {"ok": False, "error": f"Missing {req}"}
    steps = []
    if upgrade_pip:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], capture_output=True, text=True)
        steps.append({"pip_upgrade": r.returncode == 0})
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], capture_output=True, text=True)
    steps.append({
        "requirements": r.returncode == 0,
        "stdout_tail": (r.stdout or "")[-500:],
        "stderr_tail": (r.stderr or "")[-500:],
    })
    ok = r.returncode == 0
    return {"ok": ok, "steps": steps}


def write_launchers() -> dict[str, Any]:
    root = repo_root()
    install_dir = root / "install"
    install_dir.mkdir(parents=True, exist_ok=True)
    # Desktop shortcut script (PowerShell) for Start Menu / Desktop
    ps1 = install_dir / "Create-Shortcuts.ps1"
    ps1.write_text(
        f'''# Create Desktop + Start Menu shortcuts for {PRODUCT_NAME}
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Desktop = [Environment]::GetFolderPath("Desktop")
$Start = Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\NEURON"
New-Item -ItemType Directory -Force -Path $Start | Out-Null
$W = New-Object -ComObject WScript.Shell
$Bat = Join-Path $Root "launch-jarvis.bat"
foreach ($pair in @(
  @((Join-Path $Desktop "NEURON.lnk"), $Bat),
  @((Join-Path $Start "NEURON.lnk"), $Bat)
)) {{
  $s = $W.CreateShortcut($pair[0])
  $s.TargetPath = $pair[1]
  $s.WorkingDirectory = $Root
  $s.Description = "{PRODUCT_NAME} {PRODUCT_VERSION}"
  $s.Save()
}}
Write-Host "Shortcuts created."
''',
        encoding="utf-8",
    )
    return {"ok": True, "shortcut_script": str(ps1)}


def mark_installed(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    marker = {
        "product": PRODUCT_NAME,
        "version": PRODUCT_VERSION,
        "installed_at": time.time(),
        "python": sys.version,
        "root": str(repo_root()),
        **(extra or {}),
    }
    install_marker_path().write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return marker


def run_install(*, with_deps: bool = True, shortcuts: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "version": PRODUCT_VERSION}
    if with_deps:
        dep = install_dependencies()
        result["dependencies"] = dep
        if not dep.get("ok"):
            result["ok"] = False
            return result
    if shortcuts:
        result["shortcuts"] = write_launchers()
        # Best-effort run shortcut script on Windows
        try:
            script = Path(result["shortcuts"]["shortcut_script"])
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            result["shortcut_error"] = str(exc)
    result["marker"] = mark_installed(extra={"with_deps": with_deps})
    return result
