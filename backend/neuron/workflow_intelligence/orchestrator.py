"""Workflow Intelligence orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.workflows import engine as wf_engine
from neuron.workflow_intelligence import learner, observe
from neuron.workflow_intelligence.apps import all_targets
from neuron.workflow_intelligence.detect import classify_wi_intent
from neuron.workflow_intelligence.learner import PRESETS
from neuron.workflow_intelligence.types import WICapability, WIResult


def dispatch(capability: str, args: dict[str, Any] | None = None) -> WIResult:
    args = args or {}

    if capability == WICapability.STATUS.value:
        rows = learner.list_intelligence_workflows()
        seq = observe.recent_app_sequence(window_s=3600.0, limit=8)
        say = (
            f"Workflow Intelligence online. Presets={len(PRESETS)}; "
            f"saved={len(rows)}; recent apps={seq or 'none'}."
        )
        return WIResult(ok=True, say=say, capability=capability, data={"workflows": rows, "recent": seq, "targets": all_targets()})

    if capability == WICapability.OBSERVE.value:
        app = str(args.get("app") or "")
        r = observe.observe(app, action=str(args.get("action") or "focus"))
        if not r.get("ok"):
            return WIResult(ok=False, error=r.get("error") or "observe failed", say=r.get("error") or "observe failed", capability=capability)
        return WIResult(ok=True, say=f"Observed {r['event'].get('app')}.", acted=True, capability=capability, data=r)

    if capability == WICapability.LEARN.value:
        r = learner.learn_from_observations(name=args.get("name"))
        if not r.get("ok"):
            # Fall back: ensure presets so learning always yields reusable workflows
            ens = learner.ensure_presets()
            return WIResult(
                ok=True,
                say=f"Not enough observations ({r.get('error')}). Seeded presets instead ({len(ens.get('presets') or [])}).",
                acted=True,
                capability=capability,
                data={"learn": r, "ensure": ens},
            )
        wid = (r.get("workflow") or {}).get("id")
        return WIResult(
            ok=True,
            say=f"Created reusable workflow {(r.get('workflow') or {}).get('name')} ({wid}).",
            acted=True,
            capability=capability,
            data=r,
        )

    if capability == WICapability.ENSURE.value:
        r = learner.ensure_presets()
        return WIResult(
            ok=True,
            say=f"Ensured presets: created={len(r.get('created') or [])}, updated={len(r.get('updated') or [])}.",
            acted=True,
            capability=capability,
            data=r,
        )

    if capability == WICapability.LIST.value:
        rows = learner.list_intelligence_workflows()
        names = ", ".join(r.get("name") or r.get("id") for r in rows[:8]) or "none"
        return WIResult(ok=True, say=f"{len(rows)} intelligent workflow(s): {names}.", capability=capability, data={"workflows": rows})

    if capability == WICapability.RUN.value:
        dry = bool(args.get("dry_run"))
        preset_key = str(args.get("preset") or "")
        if preset_key and preset_key in PRESETS:
            preset = PRESETS[preset_key]
            # Observe the session apps, ensure workflow exists, then run
            observe.observe_targets(list(preset["apps"]), action="preset_run")
            wf = learner.upsert_workflow(
                preset["name"],
                apps=list(preset["apps"]),
                description=str(preset.get("description") or ""),
                tags=list(preset.get("tags") or []),
            )
            if dry:
                return WIResult(
                    ok=True,
                    say=f"Would run '{wf.name}' ({len(wf.steps)} steps).",
                    acted=False,
                    capability=capability,
                    data={"workflow": wf.summary(), "dry_run": True},
                )
            result = wf_engine.run_workflow(wf.id, dry_run=False)
            ok = bool(result.get("ok", True)) if "ok" in result else True
            # replay may use different ok shape
            if result.get("error") and not result.get("ok"):
                ok = False
            say = f"Ran '{wf.name}'." if ok else f"Workflow '{wf.name}' finished with issues: {result.get('error') or result}"
            return WIResult(ok=ok, say=say, acted=True, capability=capability, data={"workflow": wf.summary(), "replay": result})

        wid = str(args.get("id") or args.get("name") or "").strip()
        if not wid:
            return WIResult(ok=False, error="Need preset or workflow id", say="Need preset or workflow id.", capability=capability)
        result = wf_engine.run_workflow(wid, dry_run=dry)
        return WIResult(ok=True, say=f"Ran workflow {wid}.", acted=True, capability=capability, data=result)

    if capability == WICapability.SUGGEST.value:
        sug = learner.suggest_for_text(str(args.get("text") or ""))
        if not sug.get("ok"):
            learner.ensure_presets()
            return WIResult(ok=True, say="Try: Start coding. Start game development. Prepare for Blender.", capability=capability, data=sug)
        return WIResult(
            ok=True,
            say=f"Suggested workflow: {sug.get('name')} ({', '.join(sug.get('apps') or [])}).",
            capability=capability,
            data=sug,
        )

    return WIResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False, dry_run: bool = False) -> tuple[str, bool, dict]:
    intent = classify_wi_intent(text)
    cap = intent.get("capability") or WICapability.SUGGEST.value
    args = dict(intent.get("args") or {})
    if dry_run:
        args["dry_run"] = True
    # Safe default: run presets for dry_run in benches; live runs open apps
    result = dispatch(cap, args)
    meta = {
        "path": "workflow_intelligence",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Workflow intelligence failed.", True, meta
