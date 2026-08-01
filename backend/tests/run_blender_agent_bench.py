"""Benchmarks for Blender Agent — bpy script generation (dry-run safe)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.blender_agent import looks_like_blender, orchestrate, dispatch, find_blender
    from neuron.blender_agent.detect import classify_blender_intent
    from neuron.blender_agent.types import BlenderCapability
    from neuron.blender_agent import scripts_gen
    from neuron.blender_agent.bridge import maybe_handle_blender

    assert not looks_like_blender("mute")
    assert not looks_like_blender("Open Chrome")
    assert looks_like_blender("Create a realistic soda can.")
    assert looks_like_blender("Render in Cycles.")
    assert looks_like_blender("Generate a procedural material.")
    assert looks_like_blender("Fix topology.")
    assert looks_like_blender("Animate this character.")
    print("OK detect")

    assert classify_blender_intent("Create a realistic soda can.")["args"].get("recipe") == "soda_can"
    assert classify_blender_intent("Render in Cycles.")["args"].get("engine") == "CYCLES"
    assert classify_blender_intent("Generate a procedural material.")["capability"] == BlenderCapability.MATERIAL.value
    print("OK classify")

    # Script generators produce valid bpy markers
    for label, src in [
        ("soda", scripts_gen.script_soda_can()),
        ("mat", scripts_gen.script_material()),
        ("geo", scripts_gen.script_geometry_nodes()),
        ("rig", scripts_gen.script_rigging()),
        ("anim", scripts_gen.script_animation()),
        ("light", scripts_gen.script_lighting()),
        ("render", scripts_gen.script_render("CYCLES")),
        ("phys", scripts_gen.script_physics()),
        ("cam", scripts_gen.script_camera()),
        ("topo", scripts_gen.script_topology_fix()),
    ]:
        assert "import bpy" in src and "NEURON_BLENDER_OK" in src, label
    print("OK script_generators")

    # Dry-run dispatch (no Blender required)
    r = dispatch(BlenderCapability.CREATE.value, {"recipe": "soda_can"}, dry_run=True)
    assert r.ok and r.script_path and Path(r.script_path).is_file()
    print(f"OK soda_can script={Path(r.script_path).name}")

    r2 = dispatch(BlenderCapability.MATERIAL.value, {}, dry_run=True)
    assert r2.ok and r2.script_path
    r3 = dispatch(BlenderCapability.RENDER.value, {"engine": "CYCLES"}, dry_run=True)
    assert r3.ok
    print("OK dry_run material/render")

    st = dispatch(BlenderCapability.STATUS.value, {})
    assert st.ok
    print(f"OK status blender={find_blender()!r}")

    assets = scripts_gen.list_assets()
    assert assets["count"] >= 1
    print(f"OK assets count={assets['count']}")

    say, acted, meta = orchestrate("Create a realistic soda can.", dry_run=True)
    assert acted and meta.get("capability") == BlenderCapability.CREATE.value
    print(f"OK orchestrate say={say[:70]!r}")

    assert maybe_handle_blender("mute") is None
    hit = maybe_handle_blender("Fix topology.")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    for name in ("blender_status", "blender_run", "blender_script"):
        assert tool_registry.get(name), name
    # Existing plugin still present
    assert tool_registry.get("blender.open") or tool_registry.get("blender_open")
    print("OK tools + plugin compose")

    print("PASS blender_agent_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
