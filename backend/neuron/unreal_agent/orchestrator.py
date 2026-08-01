"""Unreal Agent orchestrator."""

from __future__ import annotations

from typing import Any

from neuron.unreal_agent import recipes, runner
from neuron.unreal_agent.detect import classify_unreal_intent
from neuron.unreal_agent.types import UnrealCapability, UnrealResult


def _run_py(path: str, src: str, *, dry_run: bool, capability: str) -> UnrealResult:
    result = runner.run_editor_python(path, dry_run=dry_run)
    dry = bool(result.get("dry_run"))
    ok = bool(result.get("ok"))
    say = (
        f"Unreal artifact ready: {path}"
        + (" (dry-run; Editor Cmd not executed)" if dry and not runner.find_editor_cmd() else "")
        + (" - executed OK." if ok and not dry else "")
        + (f" - error: {str(result.get('stderr') or '')[:160]}" if not ok and not dry else "")
    )
    return UnrealResult(
        ok=ok or dry,
        say=say,
        acted=ok and not dry,
        capability=capability,
        artifact_path=path,
        data=result,
        dry_run=dry,
        error="" if ok or dry else str(result.get("stderr") or ""),
    )


def dispatch(capability: str, args: dict[str, Any] | None = None, *, dry_run: bool = False) -> UnrealResult:
    args = args or {}

    if capability == UnrealCapability.STATUS.value:
        eng = runner.find_engine()
        editor = runner.find_editor_cmd(eng)
        uat = runner.find_uat(eng)
        proj = runner.find_uproject()
        return UnrealResult(
            ok=True,
            say=(
                f"Unreal Agent online. Engine={'found' if eng else 'not found'}; "
                f"EditorCmd={'yes' if editor else 'no'}; UAT={'yes' if uat else 'no'}; "
                f"Project={proj or 'none'}."
            ),
            capability=capability,
            data={"engine": eng, "editor": editor, "uat": uat, "project": proj, "assets": str(runner.assets_root())},
        )

    if capability == UnrealCapability.OPEN.value:
        r = runner.open_unreal()
        return UnrealResult(ok=True, say="Opening Unreal / project.", acted=True, capability=capability, data={"result": r})

    if capability == UnrealCapability.CHARACTER.value:
        path, _ = recipes.script_third_person_character(str(args.get("name") or "TP_Character"))
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.NIAGARA.value:
        path, _ = recipes.script_niagara_fire(str(args.get("name") or "NS_Fire"))
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.MATERIAL.value:
        path, _ = recipes.script_material()
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.LANDSCAPE.value:
        path, _ = recipes.script_landscape()
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.LIGHTING.value:
        path, _ = recipes.script_lighting()
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.SEQUENCER.value:
        path, _ = recipes.script_sequencer()
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.ANIMATION.value:
        path, _ = recipes.script_animation_notes()
        return _run_py(path, "", dry_run=dry_run, capability=capability)

    if capability == UnrealCapability.BLUEPRINT.value:
        p = recipes.blueprint_guide(str(args.get("kind") or "generic"))
        return UnrealResult(ok=True, say=f"Blueprint guide written: {p.name}", capability=capability, artifact_path=str(p))

    if capability == UnrealCapability.CPP.value:
        p = recipes.cpp_actor_stub(str(args.get("name") or "NeuronActor"))
        return UnrealResult(ok=True, say=f"C++ actor stub: {p}", capability=capability, artifact_path=str(p))

    if capability == UnrealCapability.OPTIMIZATION.value:
        plan = recipes.optimization_plan()
        tips = "; ".join(plan["tips"][:3])
        return UnrealResult(
            ok=True,
            say=f"FPS optimization plan saved. Top tips: {tips}",
            capability=capability,
            artifact_path=plan["path"],
            data=plan,
            suggestions=plan["tips"],
        )

    if capability == UnrealCapability.PACKAGING.value:
        plan = recipes.packaging_plan(runner.find_uproject())
        if args.get("execute"):
            result = runner.run_uat(plan["uat_args"], dry_run=dry_run)
            return UnrealResult(
                ok=bool(result.get("ok")) or bool(result.get("dry_run")),
                say="Packaging via UAT " + ("dry-run ready" if result.get("dry_run") else ("OK" if result.get("ok") else "failed")),
                acted=bool(result.get("ok")) and not result.get("dry_run"),
                capability=capability,
                artifact_path=plan["path"],
                data={"plan": plan, "result": result},
                dry_run=bool(result.get("dry_run")),
                suggestions=plan.get("notes") or [],
            )
        return UnrealResult(
            ok=True,
            say=f"Package plan ready (UAT BuildCookRun). Confirm to execute. Args saved to {plan['path']}",
            capability=capability,
            artifact_path=plan["path"],
            data=plan,
            suggestions=plan.get("notes") or [],
        )

    if capability == UnrealCapability.BUILD.value:
        plan = recipes.build_monitor_plan(runner.find_uproject())
        return UnrealResult(
            ok=True,
            say="Build monitoring checklist ready: watch UBT logs, ShaderCompileWorker, Live Coding.",
            capability=capability,
            data=plan,
            suggestions=plan.get("commands") or [],
        )

    if capability == UnrealCapability.CRASH.value:
        data = recipes.parse_crash(str(args.get("text") or ""))
        return UnrealResult(
            ok=True,
            say=f"Crash analysis: {data.get('primary')}",
            capability=capability,
            artifact_path=data.get("path") or "",
            data=data,
            suggestions=data.get("advice") or [],
        )

    if capability == UnrealCapability.PROJECT.value:
        return UnrealResult(
            ok=True,
            say=f"Project: {runner.find_uproject() or 'none found'}; Engine: {runner.find_engine() or 'none'}",
            capability=capability,
            data={"project": runner.find_uproject(), "engine": runner.find_engine()},
        )

    if capability == UnrealCapability.RUN_SCRIPT.value:
        src = str(args.get("source") or "")
        if not src:
            return UnrealResult(ok=False, error="Need Unreal Python source.", capability=capability)
        path = runner.write_text(f"scripts/custom_{int(__import__('time').time()) % 100000}.py", src if "unreal" in src else recipes._py_header() + src)
        return _run_py(str(path), src, dry_run=dry_run, capability=capability)

    return UnrealResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False, dry_run: bool | None = None) -> tuple[str, bool, dict]:
    intent = classify_unreal_intent(text)
    cap = intent.get("capability") or UnrealCapability.STATUS.value
    args = dict(intent.get("args") or {})
    if confirmed and cap == UnrealCapability.PACKAGING.value:
        args["execute"] = True
    if dry_run is None:
        dry_run = runner.find_editor_cmd() is None and cap not in (
            UnrealCapability.OPEN.value,
            UnrealCapability.STATUS.value,
            UnrealCapability.OPTIMIZATION.value,
            UnrealCapability.BUILD.value,
            UnrealCapability.CRASH.value,
            UnrealCapability.BLUEPRINT.value,
            UnrealCapability.CPP.value,
            UnrealCapability.PACKAGING.value,
            UnrealCapability.PROJECT.value,
        )
    # Packaging without execute still just writes plan
    if cap == UnrealCapability.PACKAGING.value and not args.get("execute"):
        dry_run = False  # plan write doesn't need editor
    result = dispatch(cap, args, dry_run=bool(dry_run))
    meta = {"path": "unreal_agent", "capability": cap, "intent": intent, "result": result.to_dict()}
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Unreal agent failed.", True, meta
