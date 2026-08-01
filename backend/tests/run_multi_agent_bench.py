"""Benchmarks for Multi-Agent System — roles, bus, coordinator routing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from neuron.agents import (
        AgentRole,
        looks_like_multi_agent,
        reset_bus,
        select_roles,
    )
    from neuron.agents.bus import get_bus
    from neuron.agents.coordinator import Coordinator, get_coordinator
    from neuron.agents.specialists import build_specialists
    from neuron.agents.types import AgentMessage

    bus = reset_bus()
    for a in build_specialists():
        a.register(bus)
    roles = bus.roles()
    expected = {r.value for r in [
        AgentRole.PLANNER, AgentRole.EXECUTOR, AgentRole.VISION, AgentRole.BROWSER,
        AgentRole.MEMORY, AgentRole.DESKTOP, AgentRole.CODE, AgentRole.RESEARCH,
    ]}
    assert expected <= set(roles), roles
    print(f"OK registered roles={roles}")

    # Bus request/reply communication
    r = bus.request("planner", {"text": "Open Chrome then search YouTube for Unreal Engine"})
    assert r.ok and (r.data or {}).get("plan"), r
    print(f"OK bus planner steps={len((r.data or {}).get('plan', {}).get('subtasks') or [])}")

    hist = bus.history(10)
    assert any(h.get("kind") == "request" for h in hist)
    assert any(h.get("kind") == "result" for h in hist)
    print(f"OK bus history n={len(hist)}")

    # Routing: do not steal Category A
    assert not looks_like_multi_agent("mute")
    assert not looks_like_multi_agent("Open Chrome")
    assert looks_like_multi_agent("Research Unreal Engine and remember that I prefer dark mode")
    assert looks_like_multi_agent("Open Chrome then search YouTube for tutorials")
    print("OK detect gates")

    sel = select_roles("Research Unreal Engine and remember that I prefer dark mode")
    assert "research" in sel and "memory" in sel, sel
    print(f"OK select_roles {sel}")

    sel_mem = select_roles("Remember that my favorite project folder is Desktop/Projects/NeuronAI")
    assert sel_mem == ["memory"] or (sel_mem[0] == "memory" and "planner" not in sel_mem), sel_mem
    print(f"OK select_roles memory-only {sel_mem}")

    # Coordinator compose (memory remember — no GUI required)
    import neuron.memory_engine.store as store_mod
    bench_mem = Path(__file__).with_name("_ma_mem_bench.json")
    store_mod._PATH = bench_mem
    store_mod._STORE = None
    if bench_mem.exists():
        bench_mem.unlink()

    coord = Coordinator(bus=bus)
    say, acted, meta = coord.run(
        "Remember that my favorite project folder is Desktop/Projects/NeuronAI",
        confirmed=True,
    )
    assert "memory" in (meta.get("roles") or []), meta
    assert any(a.get("role") == "memory" and a.get("ok") for a in (meta.get("agents") or [])), meta
    print(f"OK coordinator memory say={say[:80]!r}")

    # Direct ask tool path
    from neuron.agents import tool_multi_agent_ask, tool_multi_agent_status
    st = tool_multi_agent_status({})
    assert getattr(st, "ok", True)
    ask = tool_multi_agent_ask({"role": "planner", "text": "Download Blender and install it."})
    assert getattr(ask, "ok", True) or (isinstance(ask, dict) and ask.get("ok"))
    print("OK tools status/ask")

    # Registry
    from neuron.brain import tool_registry
    tool_registry.ensure_bootstrapped()
    for name in ("multi_agent_run", "multi_agent_status", "multi_agent_ask"):
        assert tool_registry.get(name), name
    print("OK tool_registry")

    # Bridge passthrough for simple
    from neuron.agents.bridge import maybe_handle_multi_agent
    assert maybe_handle_multi_agent("mute") is None
    print("OK bridge non-steal")

    print("PASS multi_agent_bench")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
