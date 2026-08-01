"""Plugin permissions + dependency checks."""

from __future__ import annotations

import re
from typing import Any

from neuron.plugins.sdk import PluginManifest

_RISK_RANK = {"safe": 0, "confirm": 1, "high": 2, "blocked": 3}


def risk_allowed(action_risk: str, ceiling: str) -> bool:
    return _RISK_RANK.get((action_risk or "safe").lower(), 1) <= _RISK_RANK.get(
        (ceiling or "confirm").lower(), 1
    )


def parse_semver(v: str) -> tuple[int, int, int]:
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", (v or "0.0.0").strip())
    if not m:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)


def satisfies(constraint: str, version: str) -> bool:
    """Minimal SemVer check: >=X.Y.Z or ==X.Y.Z or bare X.Y.Z as >="""
    c = (constraint or "").strip()
    ver = parse_semver(version)
    if not c:
        return True
    if c.startswith(">="):
        return ver >= parse_semver(c[2:])
    if c.startswith("=="):
        return ver == parse_semver(c[2:])
    if c.startswith(">"):
        return ver > parse_semver(c[1:])
    return ver >= parse_semver(c)


def check_dependencies(manifest: PluginManifest, *, neuron_version: str = "4.10.0") -> list[str]:
    """Return list of unmet dependency messages (empty = OK)."""
    errors: list[str] = []
    dep = manifest.dependencies
    if not satisfies(dep.neuron, neuron_version):
        errors.append(f"Requires neuron {dep.neuron}, have {neuron_version}")
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        for t in dep.tools:
            if not tool_registry.get(t) and not tool_registry.get(t.replace(".", "_")):
                errors.append(f"Missing required tool: {t}")
    except Exception as exc:
        errors.append(f"Tool check failed: {exc}")
    for pkg in dep.python:
        try:
            __import__(pkg)
        except Exception:
            errors.append(f"Missing python package: {pkg}")
    if dep.plugins:
        try:
            from neuron.plugins import loader
            loaded = {p.get("id") for p in loader.list_plugins() if p.get("enabled")}
            discovered: set[str] = set()
            for root in loader.discover():
                try:
                    data = json_loads_manifest(root)
                    if data.get("id"):
                        discovered.add(str(data["id"]))
                except Exception:
                    continue
            for pid in dep.plugins:
                if pid in loaded or pid in discovered:
                    continue
                errors.append(f"Missing required plugin: {pid}")
        except Exception as exc:
            errors.append(f"Plugin dependency check failed: {exc}")
    return errors


def json_loads_manifest(root) -> dict:
    import json
    from pathlib import Path
    return json.loads(Path(root).joinpath("plugin.json").read_text(encoding="utf-8"))


def compare_versions(a: str, b: str) -> int:
    """Return -1 if a<b, 0 if equal, 1 if a>b."""
    pa, pb = parse_semver(a), parse_semver(b)
    return (pa > pb) - (pa < pb)


def validate_manifest(manifest: PluginManifest) -> list[str]:
    errs: list[str] = []
    if not manifest.id or not re.match(r"^[a-z][a-z0-9_.-]+$", manifest.id):
        errs.append("Invalid plugin id")
    if not manifest.version:
        errs.append("Missing version")
    for a in manifest.actions:
        if not a.name:
            errs.append("Action missing name")
        if not risk_allowed(a.risk, manifest.permissions.risk_ceiling):
            errs.append(f"Action {a.name} risk {a.risk} exceeds ceiling {manifest.permissions.risk_ceiling}")
        if a.risk == "high" and not manifest.permissions.allow_shell and "shell" in a.name:
            errs.append(f"Action {a.name} blocked: shell not permitted")
    return errs
