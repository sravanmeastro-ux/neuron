"""Validated PowerShell runner."""

from __future__ import annotations

import subprocess

from neuron.safety import policy


def run_powershell(args: dict) -> str:
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return "Need a PowerShell command."
    ok, reason = policy.allow("run_powershell", {"command": cmd}, confirmed=bool(args.get("confirmed")))
    if not ok:
        return reason
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=float(args.get("timeout") or 20),
        )
        out = (completed.stdout or "").strip() or (completed.stderr or "").strip()
        if completed.returncode != 0:
            return f"PowerShell error ({completed.returncode}): {out[:500]}"
        return out[:800] or "OK."
    except Exception as exc:
        return f"PowerShell failed: {exc}"
