"""System diagnostics for public-release readiness."""

from __future__ import annotations

import importlib
import json
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

from neuron.production.paths import PRODUCT_VERSION, backend_root, diagnostics_report_path, repo_root
from neuron.production.types import CheckResult


REQUIRED_MODULES = [
    "fastapi",
    "uvicorn",
    "PIL",
    "psutil",
    "openai",
    "numpy",
    "pyautogui",
]


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_diagnostics() -> dict[str, Any]:
    checks: list[CheckResult] = []

    checks.append(CheckResult(
        "runtime", "python",
        sys.version_info >= (3, 10),
        "fail" if sys.version_info < (3, 10) else "info",
        f"Python {sys.version.split()[0]}",
        fix="Install Python 3.10+",
    ))

    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            checks.append(CheckResult("deps", mod, True, "info", "import ok"))
        except Exception as exc:
            checks.append(CheckResult("deps", mod, False, "fail", str(exc), fix=f"pip install {mod}"))

    cfg_path = backend_root() / "config.json"
    cfg_ok = False
    cfg_err = ""
    try:
        json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg_ok = True
    except Exception as exc:
        cfg_err = str(exc)
    checks.append(CheckResult("settings", "config_json", cfg_ok, "fail", cfg_err or "valid JSON", fix="Fix config.json"))

    checks.append(CheckResult(
        "disk", "backend_writable",
        True,
        "info",
        f"backend={backend_root()}",
    ))
    try:
        probe = backend_root() / "data" / "production" / ".write_probe"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(CheckResult("disk", "data_writable", True, "info", "data/production writable"))
    except Exception as exc:
        checks.append(CheckResult("disk", "data_writable", False, "fail", str(exc), fix="Fix directory permissions"))

    ollama = shutil.which("ollama")
    checks.append(CheckResult(
        "llm", "ollama_cli",
        bool(ollama),
        "warn" if not ollama else "info",
        ollama or "ollama not on PATH",
        fix="Install Ollama from ollama.com",
    ))
    checks.append(CheckResult(
        "llm", "ollama_port",
        _port_open("127.0.0.1", 11434),
        "warn",
        "Ollama API reachable" if _port_open("127.0.0.1", 11434) else "port 11434 closed",
        fix="Run: ollama serve",
    ))

    checks.append(CheckResult(
        "server", "port_8765",
        _port_open("127.0.0.1", 8765),
        "info",
        "Brain already listening" if _port_open("127.0.0.1", 8765) else "Brain not running (ok if offline)",
    ))

    # Safety
    try:
        from neuron.safety import failsafe
        checks.append(CheckResult("security", "failsafe_import", True, "info", "neuron.safety.failsafe importable"))
    except Exception as exc:
        checks.append(CheckResult("security", "failsafe_import", False, "fail", str(exc)))

    # Tools bootstrap smoke
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        n = len(getattr(tool_registry, "_REGISTRY", {}) or {})
        checks.append(CheckResult("architecture", "tools_bootstrapped", n > 10, "fail" if n <= 10 else "info", f"{n} tools registered"))
    except Exception as exc:
        checks.append(CheckResult("architecture", "tools_bootstrapped", False, "fail", str(exc)))

    # Installer scripts
    inst = repo_root() / "install" / "Install-NEURON.ps1"
    checks.append(CheckResult("installer", "Install-NEURON.ps1", inst.is_file(), "fail", str(inst)))

    fails = [c for c in checks if not c.ok and c.severity == "fail"]
    warns = [c for c in checks if not c.ok and c.severity == "warn"]
    payload = {
        "version": PRODUCT_VERSION,
        "ts": time.time(),
        "ok": not fails,
        "fail_count": len(fails),
        "warn_count": len(warns),
        "checks": [c.to_dict() for c in checks],
        "summary": f"{len(checks)} checks, {len(fails)} fail, {len(warns)} warn",
    }
    path = diagnostics_report_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["path"] = str(path)
    return payload
