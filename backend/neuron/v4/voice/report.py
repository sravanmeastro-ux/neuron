"""Migration readiness report builder."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from neuron.v4.voice.config import procedure_learning_off, voice_config_snapshot
from neuron.v4.voice.types import MigrationReadinessReport, voice_metrics

REPORT_PATH = Path(__file__).resolve().parents[3] / "tests" / "v4_voice_migration_report.json"


def build_migration_report(
    *,
    mock_parity_pass: bool = False,
    shadow_parity_pass: bool = False,
    live_parity_pass: str = "NOT_RUN",
    safety_pass: bool = False,
    false_success_pass: bool = False,
    recovery_loop_pass: bool = False,
    context_pass: bool = False,
    latency_pass: bool = False,
    canary_sample_count: int = 0,
    live_sample_count: int = 0,
    soak_status: str = "NOT_RUN",
    extra_metrics: dict[str, Any] | None = None,
) -> MigrationReadinessReport:
    blockers: list[str] = []
    snap = voice_config_snapshot()
    if snap.get("voice_routing_mode") != "LEGACY" and snap.get("configured_mode") == "HIERARCHICAL":
        # Config may be LEGACY due to flag — ok
        pass
    if not procedure_learning_off():
        blockers.append("procedure_learning_enabled must be false during migration")
    if live_parity_pass in (False, "FAIL"):
        blockers.append("LIVE parity failed")
    elif live_parity_pass == "NOT_RUN":
        blockers.append("LIVE parity NOT_RUN (required before default switch)")
    if soak_status == "NOT_RUN":
        blockers.append("LIVE soak NOT_RUN (required before default switch)")
    elif soak_status in (False, "FAIL"):
        blockers.append("LIVE soak failed")
    if canary_sample_count < 20:
        blockers.append(f"canary_sample_count={canary_sample_count} < 20")
    if live_sample_count < 20:
        blockers.append(f"live_sample_count={live_sample_count} < 20")
    if not mock_parity_pass:
        blockers.append("mock parity not passed")
    if not shadow_parity_pass:
        blockers.append("shadow parity not passed")
    if not safety_pass:
        blockers.append("safety gate not passed")
    if not false_success_pass:
        blockers.append("false-success gate not passed")
    if not recovery_loop_pass:
        blockers.append("recovery-loop gate not passed")
    if not context_pass:
        blockers.append("context gate not passed")
    if not latency_pass:
        blockers.append("latency gate not measured/passed")

    if str(snap.get("configured_mode") or "").upper() == "HIERARCHICAL":
        blockers.append("voice_routing_mode already HIERARCHICAL — do not treat as pre-default validation")

    # Default must remain non-HIERARCHICAL for this phase's safety posture
    default_legacy = str(snap.get("configured_mode") or "LEGACY").upper() in ("LEGACY", "SHADOW", "CANARY")

    rep = MigrationReadinessReport(
        mock_parity_pass=mock_parity_pass,
        shadow_parity_pass=shadow_parity_pass,
        live_parity_pass=live_parity_pass if isinstance(live_parity_pass, str) else (
            "PASS" if live_parity_pass else "FAIL"
        ),
        safety_pass=safety_pass,
        false_success_pass=false_success_pass,
        recovery_loop_pass=recovery_loop_pass,
        context_pass=context_pass,
        latency_pass=latency_pass,
        canary_sample_count=canary_sample_count,
        live_sample_count=live_sample_count,
        soak_status=soak_status,
        procedure_learning_off=procedure_learning_off(),
        default_still_legacy=bool(default_legacy),
        blockers=blockers,
        metrics={
            **voice_metrics(),
            **(extra_metrics or {}),
            "voice_config": snap,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    return rep


def write_migration_report(rep: MigrationReadinessReport, path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    payload = {
        "phase": "V4.10",
        "ready_for_default": rep.ready_for_default,
        "report": rep.to_dict(),
        "rollback": {
            "steps": [
                "Set agent.hierarchical_voice_enabled=false",
                "Set agent.voice_routing_mode=LEGACY",
                "Restart server / reload config",
                "Pending confirmations: say cancel / Neuron stop",
            ],
            "note": "Config-only rollback; no code revert required.",
        },
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


__all__ = [
    "MigrationReadinessReport",
    "build_migration_report",
    "write_migration_report",
    "REPORT_PATH",
]
