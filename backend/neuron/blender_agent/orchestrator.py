"""Blender Agent orchestrator — generate bpy scripts and run via Blender CLI."""

from __future__ import annotations

from typing import Any

from neuron.blender_agent import runner, scripts_gen
from neuron.blender_agent.detect import classify_blender_intent
from neuron.blender_agent.types import BlenderCapability, BlenderResult


def _execute(name: str, source: str, *, dry_run: bool = False, background: bool = True) -> BlenderResult:
    path = runner.write_script(name, source)
    # Extract output path hint from script if present
    out_hint = ""
    for line in source.splitlines():
        if "save_as_mainfile" in line or "filepath=r\"" in line and ("exports" in line or "renders" in line):
            if "filepath=r\"" in line:
                try:
                    out_hint = line.split("filepath=r\"", 1)[1].split("\"", 1)[0]
                except Exception:
                    pass
    result = runner.run_script(path, background=background, dry_run=dry_run)
    ok = bool(result.get("ok"))
    dry = bool(result.get("dry_run"))
    say = (
        f"Blender script ready: {path.name}"
        + (f" -> {out_hint}" if out_hint else "")
        + (" (dry-run; Blender not executed)" if dry and not runner.find_blender() else "")
        + (" - executed OK." if ok and not dry else "")
        + (f" - error: {result.get('stderr', '')[:160]}" if not ok and not dry else "")
    )
    return BlenderResult(
        ok=ok or dry,  # dry-run with saved script counts as success for agent UX
        say=say,
        acted=ok and not dry,
        capability=name,
        script_path=str(path),
        output_path=out_hint,
        data=result,
        dry_run=dry,
        error="" if ok or dry else str(result.get("stderr") or ""),
    )


def dispatch(capability: str, args: dict[str, Any] | None = None, *, dry_run: bool = False) -> BlenderResult:
    args = args or {}

    if capability == BlenderCapability.STATUS.value:
        blender = runner.find_blender()
        assets = scripts_gen.list_assets()
        return BlenderResult(
            ok=True,
            say=(
                f"Blender Agent online. "
                f"Blender={'found: ' + blender if blender else 'not found (scripts still generated)'}. "
                f"Assets={assets.get('count', 0)}."
            ),
            capability=capability,
            data={"blender": blender, "assets": assets},
        )

    if capability == BlenderCapability.OPEN.value:
        r = runner.open_blender_app()
        return BlenderResult(ok=True, say="Opening Blender.", acted=True, capability=capability, data={"result": str(r)[:200]})

    if capability == BlenderCapability.ASSETS.value:
        assets = scripts_gen.list_assets()
        names = [f["name"] for f in assets.get("files") or []][-10:]
        return BlenderResult(
            ok=True,
            say=f"Asset library ({assets.get('count')} files): {', '.join(names) or 'empty'}",
            capability=capability,
            data=assets,
        )

    if capability == BlenderCapability.CREATE.value:
        if args.get("recipe") == "soda_can" or args.get("soda"):
            return _execute("soda_can", scripts_gen.script_soda_can(), dry_run=dry_run)
        kind = str(args.get("kind") or "cube")
        return _execute(f"create_{kind}", scripts_gen.script_create_object(kind), dry_run=dry_run)

    if capability == BlenderCapability.MATERIAL.value:
        return _execute("material", scripts_gen.script_material(style=str(args.get("style") or "procedural")), dry_run=dry_run)

    if capability == BlenderCapability.GEONODES.value:
        return _execute("geometry_nodes", scripts_gen.script_geometry_nodes(), dry_run=dry_run)

    if capability == BlenderCapability.LIGHTING.value:
        return _execute("lighting", scripts_gen.script_lighting(), dry_run=dry_run)

    if capability == BlenderCapability.CAMERA.value:
        return _execute("camera", scripts_gen.script_camera(), dry_run=dry_run)

    if capability == BlenderCapability.RENDER.value:
        engine = str(args.get("engine") or "CYCLES")
        return _execute("render", scripts_gen.script_render(engine=engine), dry_run=dry_run)

    if capability == BlenderCapability.ANIMATION.value:
        return _execute("animation", scripts_gen.script_animation(), dry_run=dry_run)

    if capability == BlenderCapability.RIGGING.value:
        return _execute("rigging", scripts_gen.script_rigging(), dry_run=dry_run)

    if capability == BlenderCapability.PHYSICS.value:
        return _execute("physics", scripts_gen.script_physics(), dry_run=dry_run)

    if capability == BlenderCapability.TOPOLOGY.value:
        return _execute("topology", scripts_gen.script_topology_fix(), dry_run=dry_run)

    if capability == BlenderCapability.TEXTURE.value:
        return _execute("texture", scripts_gen.script_texture(), dry_run=dry_run)

    if capability == BlenderCapability.IMPORT.value:
        path = str(args.get("path") or "").strip()
        if not path:
            return BlenderResult(ok=False, error="Import needs a file path.", capability=capability)
        return _execute("import", scripts_gen.script_import(path), dry_run=dry_run)

    if capability == BlenderCapability.EXPORT.value:
        fmt = str(args.get("format") or "glb")
        out = str(args.get("path") or (runner.assets_root() / "exports" / f"export.{fmt}"))
        return _execute("export", scripts_gen.script_export(out, fmt=fmt), dry_run=dry_run)

    if capability == BlenderCapability.RUN_SCRIPT.value:
        src = str(args.get("source") or args.get("code") or "")
        if not src:
            return BlenderResult(ok=False, error="Need bpy source.", capability=capability)
        return _execute("custom", src if "import bpy" in src else scripts_gen._header() + src, dry_run=dry_run)

    return BlenderResult(ok=False, error=f"Unknown capability: {capability}", capability=capability)


def orchestrate(text: str, *, confirmed: bool = False, dry_run: bool | None = None) -> tuple[str, bool, dict]:
    intent = classify_blender_intent(text)
    cap = intent.get("capability") or BlenderCapability.STATUS.value
    args = dict(intent.get("args") or {})
    # Default: run if Blender present; dry_run forced when no blender unless confirmed wants open only
    if dry_run is None:
        dry_run = runner.find_blender() is None and cap not in (
            BlenderCapability.OPEN.value,
            BlenderCapability.STATUS.value,
            BlenderCapability.ASSETS.value,
        )
    result = dispatch(cap, args, dry_run=bool(dry_run))
    meta = {
        "path": "blender_agent",
        "capability": cap,
        "intent": intent,
        "result": result.to_dict(),
    }
    if result.ok:
        return result.say, True, meta
    return result.error or result.say or "Blender agent failed.", True, meta
