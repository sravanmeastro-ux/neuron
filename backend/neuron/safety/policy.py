"""Risk policy — block / confirm dangerous tools."""

from __future__ import annotations

import re

from neuron.catalog import DEFAULT_RISK
from neuron.brain import tool_registry

# Shell deny patterns
_DENY_SHELL = re.compile(
    r"(?i)(\bformat\s+[a-z]:|\brm\s+-rf\b|\bdel\s+/[sf]\b|\bRemove-Item\b.*(-Recurse|-Force)|"
    r"\bshutdown\b|\bRestart-Computer\b|\bStop-Computer\b|\bInvoke-Expression\s*\(|"
    r"\biex\s*\(|DownloadString|BitLocker|\bnet\s+user\s+\w+\s+/add\b)"
)

_ALLOW_PS = re.compile(
    r"^(Get-|Select-|Write-Output|echo |dir |ls |pwd|whoami|Get-Process|"
    r"Get-Service|Get-ChildItem|Test-Path|Resolve-Path)",
    re.I,
)

_pending_confirm: dict | None = None


def set_pending(confirm: dict | None) -> None:
    global _pending_confirm
    _pending_confirm = confirm


def get_pending() -> dict | None:
    return _pending_confirm


def clear_pending() -> dict | None:
    global _pending_confirm
    p = _pending_confirm
    _pending_confirm = None
    return p


def risk_of(name: str) -> str:
    spec = tool_registry.get(name)
    if spec:
        return spec.risk
    return DEFAULT_RISK.get(name, "medium")


def requires_confirm(name: str, args: dict | None = None) -> bool:
    if risk_of(name) in ("confirm", "high") and name in ("run_shell", "run_powershell"):
        cmd = str((args or {}).get("command") or "")
        # Read-only PowerShell can skip confirm
        if name == "run_powershell" and _ALLOW_PS.search(cmd.strip()):
            return False
        return True
    return risk_of(name) == "confirm"


def allow(name: str, args: dict | None = None, *, confirmed: bool = False) -> tuple[bool, str]:
    args = args or {}
    if name in ("run_shell", "run_powershell"):
        cmd = str(args.get("command") or "")
        if _DENY_SHELL.search(cmd):
            return False, f"Blocked dangerous command: {cmd[:80]}"
        if name == "run_powershell" and not _ALLOW_PS.search(cmd.strip()) and not confirmed:
            return False, "PowerShell needs confirmation (not on allowlist)"
        if name == "run_shell" and not confirmed:
            return False, "Shell commands require confirmation — say 'confirm' after asking"
        if name == "run_shell" and confirmed:
            return True, ""
        if name == "run_powershell" and (_ALLOW_PS.search(cmd.strip()) or confirmed):
            return True, ""
        return False, "Shell blocked"
    if requires_confirm(name, args) and not confirmed:
        return False, f"{name} requires confirmation"
    return True, ""
