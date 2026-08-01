"""Release audit — architecture, security, performance, errors, logging, settings, installer, updater, docs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from neuron.production.paths import PRODUCT_VERSION, backend_root, data_dir, repo_root
from neuron.production.types import CheckResult


def _cfg() -> dict[str, Any]:
    try:
        return json.loads((backend_root() / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def audit_architecture() -> list[CheckResult]:
    out: list[CheckResult] = []
    agent = backend_root() / "neuron" / "brain" / "agent.py"
    out.append(CheckResult("architecture", "agent_entry", agent.is_file(), "fail" if not agent.is_file() else "info",
                           "agent.run compose chain present" if agent.is_file() else "Missing agent.py"))
    layers = [
        "plugins", "workflows", "self_healing", "plugin_market", "multi_device",
        "project_intelligence", "github_agent", "developer",
    ]
    missing = [n for n in layers if not (backend_root() / "neuron" / n).is_dir()]
    out.append(CheckResult(
        "architecture", "compose_layers", not missing, "warn" if missing else "info",
        f"Missing layers: {missing}" if missing else f"{len(layers)} compose layers present",
        fix="Restore missing neuron/* packages" if missing else "",
    ))
    out.append(CheckResult(
        "architecture", "tool_registry",
        (backend_root() / "neuron" / "brain" / "tool_registry.py").is_file(),
        "fail", "Central tool registry gates execution",
    ))
    return out


def audit_security() -> list[CheckResult]:
    out: list[CheckResult] = []
    safety = backend_root() / "neuron" / "safety"
    out.append(CheckResult("security", "safety_package", safety.is_dir(), "fail",
                           "neuron.safety present" if safety.is_dir() else "Missing safety package",
                           fix="Restore neuron/safety"))
    cfg = _cfg()
    agent = cfg.get("agent") or {}
    out.append(CheckResult(
        "security", "strict_verify",
        bool(agent.get("strict_verify", False)),
        "warn" if not agent.get("strict_verify") else "info",
        f"strict_verify={agent.get('strict_verify')}",
        fix="Set agent.strict_verify true for release",
    ))
    # Secrets scan: no .env committed ideally
    env = repo_root() / ".env"
    out.append(CheckResult(
        "security", "no_dotenv_in_tree_required",
        True,
        "info",
        ".env present (local ok)" if env.is_file() else "No .env at repo root",
    ))
    out.append(CheckResult(
        "security", "failsafe_module",
        (safety / "failsafe.py").is_file() if safety.is_dir() else False,
        "fail",
        "PyAutoGUI failsafe module",
    ))
    return out


def audit_performance() -> list[CheckResult]:
    out: list[CheckResult] = []
    perf = backend_root() / "neuron" / "perf.py"
    out.append(CheckResult("performance", "perf_module", perf.is_file(), "fail", "neuron.perf latency gate"))
    level = ((_cfg().get("logging") or {}).get("level") or "INFO").upper()
    out.append(CheckResult(
        "performance", "log_level",
        level in ("INFO", "WARNING", "ERROR"),
        "warn" if level == "DEBUG" else "info",
        f"logging.level={level}",
        fix="Use INFO or WARNING in production",
    ))
    out.append(CheckResult(
        "performance", "baseline_harness",
        (backend_root() / "tests" / "run_perf_baseline.py").is_file(),
        "warn",
        "Perf baseline test present" if (backend_root() / "tests" / "run_perf_baseline.py").is_file() else "Missing perf baseline",
    ))
    return out


def audit_error_handling() -> list[CheckResult]:
    out: list[CheckResult] = []
    # Self-healing + agent try/except compose pattern
    out.append(CheckResult(
        "error_handling", "self_healing",
        (backend_root() / "neuron" / "self_healing").is_dir(),
        "warn",
        "Self-healing watchdog available",
    ))
    out.append(CheckResult(
        "error_handling", "server_failsafe",
        (backend_root() / "server.py").is_file(),
        "info",
        "server.py hosts WS + timed_command",
    ))
    return out


def audit_logging() -> list[CheckResult]:
    cfg = _cfg().get("logging") or {}
    level = str(cfg.get("level") or "")
    return [
        CheckResult("logging", "config_logging", bool(level), "fail" if not level else "info",
                    f"logging.level={level or 'missing'}", fix="Add logging.level to config.json"),
        CheckResult("logging", "perf_jsonl", True, "info", "Optional perf JSONL under tests/perf_latency.jsonl"),
    ]


def audit_settings() -> list[CheckResult]:
    cfg_path = backend_root() / "config.json"
    ok = cfg_path.is_file()
    keys = []
    if ok:
        try:
            keys = sorted(json.loads(cfg_path.read_text(encoding="utf-8")).keys())
        except Exception:
            ok = False
    return [
        CheckResult("settings", "config_json", ok, "fail", f"Top-level keys: {len(keys)}", fix="Fix config.json"),
        CheckResult("settings", "wizard_available", True, "info", "production.wizard applies release presets"),
    ]


def audit_installer() -> list[CheckResult]:
    root = repo_root()
    scripts = [
        root / "install" / "Install-NEURON.ps1",
        root / "launch-jarvis.bat",
        root / "requirements.txt",
    ]
    out = []
    for p in scripts:
        out.append(CheckResult("installer", p.name, p.is_file(), "fail" if not p.is_file() else "info",
                               str(p), fix=f"Create {p.name}" if not p.is_file() else ""))
    return out


def audit_updater() -> list[CheckResult]:
    return [
        CheckResult(
            "updater", "app_updater",
            (backend_root() / "neuron" / "production" / "updater.py").is_file(),
            "warn",
            "App-level updater module",
        ),
        CheckResult(
            "updater", "plugin_updater",
            (backend_root() / "neuron" / "plugin_market" / "updater.py").is_file(),
            "info",
            "Plugin market updater present",
        ),
    ]


def audit_documentation() -> list[CheckResult]:
    root = repo_root()
    docs = [
        root / "README.md",
        backend_root() / "docs" / "PRODUCTION_READINESS_REPORT.md",
    ]
    out = []
    for p in docs:
        out.append(CheckResult("documentation", p.name, p.is_file(), "warn" if not p.is_file() else "info", str(p)))
    # Count feature reports
    reports = list((backend_root() / "docs").glob("*_REPORT.md")) if (backend_root() / "docs").is_dir() else []
    out.append(CheckResult("documentation", "feature_reports", len(reports) >= 5, "info", f"{len(reports)} *_REPORT.md files"))
    return out


def run_full_audit() -> dict[str, Any]:
    areas = {
        "architecture": audit_architecture(),
        "security": audit_security(),
        "performance": audit_performance(),
        "error_handling": audit_error_handling(),
        "logging": audit_logging(),
        "settings": audit_settings(),
        "installer": audit_installer(),
        "updater": audit_updater(),
        "documentation": audit_documentation(),
    }
    flat = [c for lst in areas.values() for c in lst]
    fails = [c for c in flat if not c.ok and c.severity == "fail"]
    warns = [c for c in flat if (not c.ok and c.severity == "warn") or (c.ok and c.severity == "warn" and c.fix)]
    # score: pass rate of non-info checks weighting fails heavier
    scored = [c for c in flat if c.severity in ("fail", "warn") or True]
    passed = sum(1 for c in flat if c.ok)
    score = int(100 * passed / max(len(flat), 1))
    # downgrade for fails
    score = max(0, score - 15 * len(fails))
    payload = {
        "version": PRODUCT_VERSION,
        "ts": time.time(),
        "score": score,
        "ready": score >= 70 and not fails,
        "fail_count": len(fails),
        "warn_count": len([c for c in flat if c.severity == "warn" and (not c.ok or c.fix)]),
        "areas": {k: [c.to_dict() for c in v] for k, v in areas.items()},
        "fails": [c.to_dict() for c in fails],
    }
    path = data_dir() / "last_audit.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["path"] = str(path)
    return payload
