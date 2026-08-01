"""Benchmarks for Unreal Agent (dry-run safe without UE install)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.unreal_agent import looks_like_unreal, orchestrate, dispatch, find_engine
    from neuron.unreal_agent.detect import classify_unreal_intent
    from neuron.unreal_agent.types import UnrealCapability
    from neuron.unreal_agent import recipes
    from neuron.unreal_agent.bridge import maybe_handle_unreal

    assert not looks_like_unreal("mute")
    assert not looks_like_unreal("Open Chrome")
    assert looks_like_unreal("Create a third-person character.")
    assert looks_like_unreal("Generate a Niagara fire effect.")
    assert looks_like_unreal("Optimize FPS.")
    assert looks_like_unreal("Package the game.")
    print("OK detect")

    assert classify_unreal_intent("Create a third-person character.")["capability"] == UnrealCapability.CHARACTER.value
    assert classify_unreal_intent("Generate a Niagara fire effect.")["capability"] == UnrealCapability.NIAGARA.value
    assert classify_unreal_intent("Optimize FPS.")["capability"] == UnrealCapability.OPTIMIZATION.value
    assert classify_unreal_intent("Package the game.")["capability"] == UnrealCapability.PACKAGING.value
    print("OK classify")

    path, src = recipes.script_third_person_character()
    assert Path(path).is_file() and "unreal" in src
    path2, src2 = recipes.script_niagara_fire()
    assert "Niagara" in src2 or "niagara" in src2.lower()
    opt = recipes.optimization_plan()
    assert len(opt["tips"]) >= 5
    pkg = recipes.packaging_plan()
    assert "BuildCookRun" in pkg["uat_args"]
    crash = recipes.parse_crash("Fatal error: Assertion failed: IsValid(Ptr)")
    assert crash["findings"]
    print("OK recipes")

    r = dispatch(UnrealCapability.CHARACTER.value, {}, dry_run=True)
    assert r.ok and r.artifact_path
    print(f"OK character artifact={Path(r.artifact_path).name}")

    r2 = dispatch(UnrealCapability.OPTIMIZATION.value, {})
    assert r2.ok and r2.suggestions
    r3 = dispatch(UnrealCapability.PACKAGING.value, {})
    assert r3.ok
    r4 = dispatch(UnrealCapability.CRASH.value, {"text": "Fatal error: Something bad"})
    assert r4.ok
    print("OK dispatch opt/package/crash")

    st = dispatch(UnrealCapability.STATUS.value, {})
    assert st.ok
    print(f"OK status engine={find_engine()!r}")

    say, acted, meta = orchestrate("Generate a Niagara fire effect.", dry_run=True)
    assert acted and meta.get("capability") == UnrealCapability.NIAGARA.value
    print(f"OK orchestrate say={say[:70]!r}")

    assert maybe_handle_unreal("mute") is None
    hit = maybe_handle_unreal("Optimize FPS.")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("unreal_status")
    assert tool_registry.get("unreal_run")
    print("OK tools")

    print("PASS unreal_agent_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
