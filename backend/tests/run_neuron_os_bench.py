"""Benchmarks for NEURON OS orchestration layer."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.os import boot, facade, looks_like_os_shell, orchestrate
    from neuron.os.detect import classify_os_intent
    from neuron.os.types import CapabilityId
    from neuron.os.bridge import maybe_handle_os

    # Category A non-steal
    assert not looks_like_os_shell("mute")
    assert not looks_like_os_shell("Open Chrome")
    assert looks_like_os_shell("os status")
    assert looks_like_os_shell("list windows")
    assert looks_like_os_shell("system monitor")
    assert looks_like_os_shell("list plugins")
    print("OK detect gates")

    rep = boot()
    assert len(rep.capabilities) >= 13, rep
    print(f"OK boot caps={len(rep.capabilities)} ms={rep.boot_ms}")

    # Intent classify
    assert classify_os_intent("os status")["kind"] == "status"
    assert classify_os_intent("launch Spotify")["capability"] == CapabilityId.LAUNCHER.value
    assert classify_os_intent("list windows")["capability"] == CapabilityId.WINDOW_MANAGER.value
    print("OK classify")

    # Facade / orchestration (safe, no destructive GUI)
    say, acted, meta = orchestrate("os status")
    assert acted and meta.get("path") == "neuron_os"
    assert "capabilities" in (meta.get("report") or {})
    print(f"OK orchestrate status say={say[:60]!r}")

    vs = facade.voice_status()
    assert vs.ok and vs.capability == CapabilityId.VOICE_FIRST.value
    print(f"OK voice_first hands_free={vs.data.get('hands_free')}")

    pl = facade.plugins()
    assert pl.capability == CapabilityId.PLUGINS.value
    print(f"OK plugins ok={pl.ok}")

    learn = facade.learning()
    assert learn.capability == CapabilityId.LEARNING.value
    print(f"OK learning ok={learn.ok}")

    # Window list (may work without side effects)
    wins = facade.windows("list")
    assert wins.capability == CapabilityId.WINDOW_MANAGER.value
    print(f"OK window_manager ok={wins.ok}")

    mon = facade.monitor()
    assert mon.capability == CapabilityId.SYSTEM_MONITOR.value
    print(f"OK system_monitor ok={mon.ok}")

    # Bridge
    assert maybe_handle_os("mute") is None
    hit = maybe_handle_os("os status")
    assert hit is not None
    print("OK bridge")

    # Tools
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    assert tool_registry.get("os_status")
    assert tool_registry.get("os_run")
    print("OK tools")

    print("PASS neuron_os_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
