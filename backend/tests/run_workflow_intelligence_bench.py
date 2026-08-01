"""Benchmarks for Workflow Intelligence."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.workflow_intelligence import looks_like_workflow_intelligence, orchestrate, dispatch
    from neuron.workflow_intelligence.detect import classify_wi_intent
    from neuron.workflow_intelligence.types import WICapability
    from neuron.workflow_intelligence import observe, learner
    from neuron.workflow_intelligence.bridge import maybe_handle_workflow_intelligence

    assert not looks_like_workflow_intelligence("mute")
    assert not looks_like_workflow_intelligence("Open Chrome")
    assert looks_like_workflow_intelligence("Start game development.")
    assert looks_like_workflow_intelligence("Start coding.")
    assert looks_like_workflow_intelligence("Prepare for Blender.")
    assert looks_like_workflow_intelligence("Learn workflow from observation")
    print("OK detect")

    assert classify_wi_intent("Start game development.")["capability"] == WICapability.RUN.value
    assert classify_wi_intent("Start coding.")["args"]["preset"] == "start_coding"
    assert classify_wi_intent("Prepare for Blender.")["args"]["preset"] == "prepare_for_blender"
    print("OK classify")

    for app in ("cursor", "github", "blender", "unreal", "vscode", "browser"):
        r = observe.observe(app)
        assert r.get("ok"), app
    print("OK observe_targets")

    ens = learner.ensure_presets()
    assert ens.get("ok") and len(ens.get("presets") or []) == 3
    print(f"OK ensure_presets created={ens.get('created')} updated={ens.get('updated')}")

    learned = learner.learn_from_observations()
    assert learned.get("ok"), learned
    print(f"OK learn source={learned.get('source')} name={(learned.get('workflow') or {}).get('name')}")

    rows = learner.list_intelligence_workflows()
    assert len(rows) >= 3
    print(f"OK list n={len(rows)}")

    # Dry-run presets (do not launch real apps in CI)
    for preset in ("start_coding", "start_game_development", "prepare_for_blender"):
        r = dispatch(WICapability.RUN.value, {"preset": preset, "dry_run": True})
        assert r.ok and r.data.get("dry_run"), preset
        print(f"OK dry_run {preset} steps={(r.data.get('workflow') or {}).get('steps')}")

    say, acted, meta = orchestrate("Start coding.", dry_run=True)
    assert acted and meta.get("capability") == WICapability.RUN.value
    print(f"OK orchestrate say={say[:80]!r}")

    assert maybe_handle_workflow_intelligence("mute") is None
    hit = maybe_handle_workflow_intelligence("List intelligent workflows")
    assert hit is not None
    print("OK bridge")

    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("workflow_intel_status")
    assert tool_registry.get("workflow_intel_run")
    print("OK tools")

    print("PASS workflow_intelligence_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
