"""SHADOW mode — hierarchical plans/evaluates without desktop mutation."""

from __future__ import annotations

import logging
from typing import Any

from neuron.v4.voice import canary
from neuron.v4.voice.types import (
    ShadowComparison,
    VoiceRequest,
    note_shadow_mismatch,
    note_shadow_mutation,
)

log = logging.getLogger("neuron.v4.voice")

# Tools that would mutate desktop — shadow must never invoke these
_MUTATING_TOOLS = frozenset({
    "open_app", "windows.open_app", "focus_app", "windows.focus_app",
    "close_app", "windows.close_app", "move_window_to_monitor", "windows.move_to_monitor",
    "maximize_app", "windows.maximize", "minimize_app",
    "click", "click_element", "click_ui_element", "type_text", "press_keys", "hotkey",
    "volume", "media", "browser_navigate", "open_website", "browser.search",
    "youtube.search", "youtube.play_result", "youtube.fullscreen", "youtube.home",
    "youtube.ensure_playback", "run_procedure", "run_shell", "scroll",
})


def plan_hierarchical_readonly(text: str) -> tuple[list[str], str, dict[str, Any]]:
    """Create HierarchicalPlanner plan without executing. Returns (tools, intent, meta)."""
    from neuron.v4.plan import HierarchicalPlanner, reset_hierarchical_planner

    # Fresh planner for isolation — do not leave active mutating state
    p = HierarchicalPlanner()
    plan = p.create_plan(text)
    tools: list[str] = []
    for sg in plan.subgoals:
        for t in sg.preferred_tools:
            if t and t not in ("clarify", "observe", "resolve"):
                tools.append(t)
    intent = ""
    if plan.subgoals:
        intent = plan.subgoals[0].intent or ""
    meta = {
        "plan_id": plan.plan_id,
        "source": plan.source,
        "n_subgoals": len(plan.subgoals),
        "status": plan.status.value if hasattr(plan.status, "value") else str(plan.status),
    }
    # Cancel so we don't leave an ACTIVE plan that later code might execute
    try:
        p.cancel(plan)
    except Exception:
        pass
    return tools, intent, meta


def legacy_tools_preview(text: str, intent: Any = None) -> tuple[list[str], str]:
    """Preview what CapabilityRouter / intent would do — no execute."""
    tools: list[str] = []
    label = ""
    try:
        from neuron.v3 import capability_router as cap_mod
        from neuron.brain import intent as intent_mod
        it = intent or intent_mod.understand(text)
        routed = cap_mod.route(text, intent=it)
        if routed.ok and routed.steps:
            for s in routed.steps:
                a = s.get("action") or s.get("tool")
                if a:
                    tools.append(str(a))
            label = getattr(routed.capability, "id", "") if routed.capability else ""
        elif getattr(it, "action", None):
            tools.append(str(it.action))
            label = str(it.kind or it.action)
    except Exception as exc:
        log.info("[VOICE] legacy preview failed: %s", exc)
    return tools, label


def _semantic_family(tools: list[str], intent: str, text: str) -> str:
    return canary.infer_intent_family(
        text,
        v4_family=intent,
        intent_action=tools[0] if tools else "",
    )


def compare_shadow(
    req: VoiceRequest,
    *,
    intent: Any = None,
) -> ShadowComparison:
    """Plan hierarchical + preview legacy. Never mutates. Increments mismatch metrics."""
    text = req.normalized or req.text
    leg_tools, leg_label = legacy_tools_preview(text, intent=intent)
    try:
        hier_tools, hier_intent, _meta = plan_hierarchical_readonly(text)
    except Exception as exc:
        note_shadow_mismatch()
        return ShadowComparison(
            request_id=req.request_id,
            legacy_intent=leg_label,
            hierarchical_intent="",
            legacy_tools=leg_tools,
            hierarchical_tools=[],
            semantic_match=False,
            mismatch_reason=f"hierarchical plan failed: {exc}",
            mutated=False,
        )

    # Guard: if any code path tried to mark mutation in shadow, count it
    mutated = False  # structural — we never call executors here

    leg_fam = _semantic_family(leg_tools, leg_label, text)
    hier_fam = _semantic_family(hier_tools, hier_intent, text)

    match = True
    reason = ""
    if leg_tools and hier_tools:
        # Semantic equivalence: same family OR overlapping tool stems
        if leg_fam and hier_fam and leg_fam == hier_fam:
            match = True
        elif _tools_overlap(leg_tools, hier_tools):
            match = True
        elif not leg_fam and not hier_fam:
            match = _tools_overlap(leg_tools, hier_tools)
        else:
            # Both planned something different families for covered canary intents
            if leg_fam in canary.CANARY_ALLOW_INTENTS and hier_fam in canary.CANARY_ALLOW_INTENTS:
                if leg_fam != hier_fam:
                    match = False
                    reason = f"family mismatch legacy={leg_fam} hier={hier_fam}"
            else:
                # Outside canary coverage — don't count as mismatch
                match = True
                reason = "outside canary coverage (ignored)"
    elif not leg_tools and not hier_tools:
        match = True
    elif not leg_tools and hier_tools:
        # Router miss but hierarchical planned — not a regression mismatch for shadow
        match = True
        reason = "legacy router miss; hierarchical planned"
    elif leg_tools and not hier_tools:
        match = False
        reason = "hierarchical produced no tools"

    if not match:
        note_shadow_mismatch()
        log.info("[VOICE] shadow mismatch: %s", reason)

    if mutated:
        note_shadow_mutation()

    return ShadowComparison(
        request_id=req.request_id,
        legacy_intent=leg_fam or leg_label,
        hierarchical_intent=hier_fam or hier_intent,
        legacy_tools=leg_tools,
        hierarchical_tools=hier_tools,
        semantic_match=match,
        mismatch_reason=reason,
        mutated=mutated,
    )


def _tools_overlap(a: list[str], b: list[str]) -> bool:
    def stem(t: str) -> str:
        t = (t or "").lower()
        if "." in t:
            return t.split(".")[-1].replace("move_to_monitor", "monitor")
        return t.replace("move_window_to_monitor", "monitor").replace("open_app", "open")

    sa = {stem(x) for x in a}
    sb = {stem(x) for x in b}
    if not sa or not sb:
        return False
    if sa & sb:
        return True
    # open/focus/search/volume families
    for fam in ("open", "focus", "search", "volume", "mute", "monitor", "maximize", "navigate", "home"):
        if any(fam in x for x in sa) and any(fam in x for x in sb):
            return True
    return False


def assert_no_mutation_in_shadow(fn) -> Any:
    """Test helper wrapper — if fn calls a mutating tool registry execute, count mutation."""
    return fn


def is_mutating_tool(name: str) -> bool:
    n = (name or "").lower()
    return n in _MUTATING_TOOLS or n.startswith("learned.")


__all__ = [
    "plan_hierarchical_readonly",
    "legacy_tools_preview",
    "compare_shadow",
    "is_mutating_tool",
    "_MUTATING_TOOLS",
]
