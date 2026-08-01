"""Production readiness orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.production import audit, diagnostics, installer, updater, wizard
from neuron.production.detect import classify_prod_intent
from neuron.production.paths import PRODUCT_NAME, PRODUCT_VERSION
from neuron.production.types import ProdCapability, ProdResult


def dispatch(capability: str, args: dict[str, Any] | None = None) -> ProdResult:
    args = args or {}

    if capability == ProdCapability.STATUS.value:
        upd = updater.check_for_updates()
        wiz = wizard.wizard_status()
        say = (
            f"{PRODUCT_NAME} {PRODUCT_VERSION}. "
            f"Update={'available' if upd.get('update_available') else 'current'}; "
            f"wizard_preset={(wiz.get('state') or {}).get('preset') or 'none'}."
        )
        return ProdResult(ok=True, say=say, capability=capability, data={"version": PRODUCT_VERSION, "updates": upd, "wizard": wiz})

    if capability == ProdCapability.AUDIT.value:
        result = audit.run_full_audit()
        say = (
            f"Release audit score {result.get('score')}/100 "
            f"({'READY' if result.get('ready') else 'NOT READY'}: "
            f"{result.get('fail_count')} fails)."
        )
        return ProdResult(ok=True, say=say, acted=True, capability=capability, data=result)

    if capability == ProdCapability.DIAGNOSTICS.value:
        result = diagnostics.run_diagnostics()
        say = f"Diagnostics: {result.get('summary')}."
        return ProdResult(ok=bool(result.get("ok")), say=say, acted=True, capability=capability, data=result)

    if capability == ProdCapability.WIZARD.value:
        preset = str(args.get("preset") or "balanced")
        if args.get("list_only"):
            return ProdResult(ok=True, say="Presets: " + ", ".join(p["id"] for p in wizard.list_presets()), capability=capability, data=wizard.wizard_status())
        r = wizard.apply_preset(preset, dry_run=bool(args.get("dry_run")))
        if not r.get("ok"):
            return ProdResult(ok=False, error=r.get("error") or "wizard failed", say=r.get("error") or "wizard failed", capability=capability, data=r)
        say = f"Applied '{r.get('label') or preset}' configuration preset." if not r.get("dry_run") else f"Would apply preset {preset}."
        return ProdResult(ok=True, say=say, acted=not bool(r.get("dry_run")), capability=capability, data=r)

    if capability == ProdCapability.INSTALL.value:
        r = installer.run_install(with_deps=bool(args.get("with_deps", True)), shortcuts=bool(args.get("shortcuts", True)))
        return ProdResult(
            ok=bool(r.get("ok")),
            say=f"Install {'complete' if r.get('ok') else 'failed'} for {PRODUCT_NAME} {PRODUCT_VERSION}.",
            acted=True,
            capability=capability,
            data=r,
            error="" if r.get("ok") else "install failed",
        )

    if capability == ProdCapability.UPDATE.value:
        r = updater.check_for_updates()
        say = (
            f"Current {r.get('current')}; latest {r.get('latest')}"
            + ("; update available." if r.get("update_available") else "; up to date.")
        )
        return ProdResult(ok=True, say=say, capability=capability, data=r)

    if capability == ProdCapability.REPORT.value:
        result = audit.run_full_audit()
        return ProdResult(ok=True, say=f"Audit saved to {result.get('path')}.", acted=True, capability=capability, data=result)

    return ProdResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False) -> tuple[str, bool, dict]:
    intent = classify_prod_intent(text)
    cap = intent.get("capability") or ProdCapability.STATUS.value
    args = dict(intent.get("args") or {})
    result = dispatch(cap, args)
    meta = {
        "path": "production",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Production readiness failed.", True, meta
