"""V4.7 Context + NLU scenario tests (mocked; no live desktop control)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neuron.v4.context import (
    ContinuityKind,
    IntentFamily,
    RouteDest,
    get_conversation_engine,
    reset_conversation_engine,
    routing_parity_check,
)
from neuron.v4.context.clarify import set_clarification, set_confirmation
from neuron.v4.context.types import ClarificationState


ROUTING_CONTEXT_MISMATCH_COUNT = 0


def _eng():
    return reset_conversation_engine()


def test_normalize_variants():
    eng = _eng()
    variants = [
        "open chrome",
        "open up chrome",
        "bring up chrome",
        "start chrome",
        "I need chrome",
        "uh open chrome please",
    ]
    canons = []
    for v in variants:
        u = eng.understand(v)
        canons.append(u.rewritten_command.lower())
        assert "chrome" in u.rewritten_command.lower()
        assert u.goal and u.goal.intent_family is IntentFamily.OPEN
    assert all("open" in c for c in canons)
    print("OK normalize variants", canons[0])


def test_negation():
    eng = _eng()
    u = eng.understand("don't open Spotify")
    assert u.route is RouteDest.REJECT
    assert u.goal and u.goal.args.get("negated")
    print("OK negation")


def test_correction_one_utterance():
    eng = _eng()
    u = eng.understand("open Spotify, no, Chrome")
    assert "chrome" in u.rewritten_command.lower()
    assert "spotify" not in u.rewritten_command.lower() or u.parsed.correction_abandoned
    print("OK self-correction", u.rewritten_command)


def test_compound():
    eng = _eng()
    u = eng.understand("open YouTube on monitor 2 and search Blender tutorials")
    assert u.goal and (
        u.goal.multi_step or u.goal.intent_family is IntentFamily.MULTI_STEP_GOAL
        or u.route is RouteDest.HIERARCHICAL
    )
    print("OK compound", u.route.value)


def test_multi_turn_continuity():
    eng = _eng()
    u1 = eng.understand("Open Chrome on monitor 2.")
    eng.apply_verified(
        action="open_app",
        args={"name": "Chrome"},
        status="SUCCESS",
        observation={"app": "Chrome"},
    )
    eng.apply_verified(
        action="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        status="SUCCESS",
        observation={"monitor": 2},
    )
    assert eng.state.task.active_application.lower() == "chrome"
    assert eng.state.task.active_monitor == 2

    u2 = eng.understand("Go to YouTube.")
    assert u2.continuity is ContinuityKind.FOLLOW_UP
    eng.apply_verified(
        action="browser_open",
        args={"site": "youtube"},
        status="SUCCESS",
        observation={"url": "https://youtube.com"},
    )
    assert "youtube" in (eng.state.task.active_browser_url or eng.state.task.active_page_hint)

    u3 = eng.understand("Search Blender tutorials.")
    assert u3.continuity is ContinuityKind.FOLLOW_UP
    eng.apply_verified(
        action="youtube.search",
        args={"query": "Blender tutorials"},
        status="SUCCESS",
    )
    assert eng.state.result_set and eng.state.result_set.is_fresh()
    assert eng.state.task.last_query.lower().startswith("blender")

    u4 = eng.understand("Play the first one.")
    assert u4.continuity is ContinuityKind.FOLLOW_UP
    assert "1" in u4.rewritten_command or "first" in u4.rewritten_command.lower() or "result" in u4.rewritten_command.lower()
    eng.apply_verified(action="youtube.play_result", args={"index": 0}, status="SUCCESS")

    u5 = eng.understand("Make it fullscreen.")
    assert u5.continuity is ContinuityKind.FOLLOW_UP
    eng.apply_verified(action="youtube.fullscreen", args={}, status="UNCERTAIN", summary="unknown")
    assert eng.state.task.media_fullscreen == "unknown"
    assert "media_fullscreen" in eng.state.task.uncertain_facts

    # Stronger observation later
    eng.apply_verified(
        action="youtube.fullscreen",
        args={},
        status="SUCCESS",
        observation={"media_fullscreen": True},
    )
    assert eng.state.task.media_fullscreen == "true"
    print("OK multi-turn continuity")


def test_result_set_and_stale():
    eng = _eng()
    eng.begin_task("search")
    eng.state.task.active_application = "Chrome"
    eng.apply_verified(action="search", args={"query": "Blender"}, status="SUCCESS")
    assert eng.state.result_set and eng.state.result_set.pick(1)
    assert eng.state.result_set.pick(2)
    eng.invalidate_result_set("navigated")
    assert not eng.state.result_set.is_fresh()
    u = eng.understand("play the first one")
    # May still follow-up linguistically but pick should fail on stale set
    assert eng.state.result_set.stale
    print("OK result set stale")


def test_correction_preserves_progress():
    eng = _eng()
    eng.begin_task("search Blender")
    eng.state.task.active_application = "Chrome"
    eng.state.task.last_query = "Blender tutorials"
    eng.apply_verified(action="search", args={"query": "Blender tutorials"}, status="SUCCESS")
    u = eng.understand("Actually play the second one.")
    assert u.continuity in (ContinuityKind.CORRECTION, ContinuityKind.FOLLOW_UP, ContinuityKind.ELLIPSIS)
    # Verified search query preserved
    assert eng.state.task.last_query.lower().startswith("blender")
    if u.goal_update:
        assert u.goal_update.preserve_verified
    print("OK correction preserve", u.rewritten_command)


def test_clarification_flow():
    eng = _eng()
    eng.set_pending_clarification(
        set_clarification(
            prompt="Which Settings: Chrome or app window?",
            original_goal="click Settings",
            options=[
                {"label": "Chrome Settings", "app": "Chrome"},
                {"label": "App Settings", "app": "App"},
            ],
            source="test",
        )
    )
    u = eng.understand("the Chrome one")
    assert u.continuity is ContinuityKind.CLARIFICATION_ANSWER
    assert u.clarification_resolution and u.clarification_resolution.get("resolved")
    assert eng.state.pending_clarification is None

    eng.set_pending_clarification(
        set_clarification(
            prompt="Which?",
            original_goal="click Settings",
            options=[{"label": "A"}, {"label": "B"}],
        )
    )
    u2 = eng.understand("second one")
    assert u2.clarification_resolution and u2.clarification_resolution.get("resolved")

    eng.set_pending_clarification(
        set_clarification(prompt="Which?", options=[{"label": "A"}, {"label": "B"}])
    )
    u3 = eng.understand("neither")
    assert u3.clarification_resolution and not u3.clarification_resolution.get("resolved")

    eng.set_pending_clarification(
        set_clarification(prompt="Which?", options=[{"label": "A"}])
    )
    u4 = eng.understand("cancel")
    assert u4.clarification_resolution and u4.clarification_resolution.get("cancel")
    print("OK clarification flow")


def test_confirmation_separate():
    eng = _eng()
    eng.set_pending_confirmation(
        set_confirmation(action="shell", args={"cmd": "rm"}, risk="HIGH", target="disk")
    )
    # Clarify-style answer must NOT authorize
    eng.state.pending_clarification = set_clarification(
        prompt="Which?",
        options=[{"label": "one"}, {"label": "two"}],
    )
    # Confirmation pending + clarify pending: confirmation checked first for yes
    # Clear clarify to test confirm
    eng.state.pending_clarification = None
    u = eng.understand("yes")
    assert u.confirmation_resolution and u.confirmation_resolution.get("authorized")

    eng.set_pending_confirmation(
        set_confirmation(action="shell", args={"cmd": "rm"}, risk="HIGH")
    )
    u2 = eng.understand("open chrome")
    # Unrelated — must not authorize
    assert not u2.confirmation_resolution or not u2.confirmation_resolution.get("authorized")
    assert eng.state.pending_confirmation and eng.state.pending_confirmation.is_active()
    print("OK confirmation separate")


def test_verified_context_rules():
    eng = _eng()
    eng.apply_verified(
        action="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        status="FAILURE",
    )
    assert eng.state.task.active_monitor != 2 or "monitor" not in eng.state.task.verified_facts
    eng.apply_verified(
        action="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        status="UNCERTAIN",
    )
    assert "monitor" in eng.state.task.uncertain_facts
    eng.apply_verified(
        action="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        status="SUCCESS",
    )
    assert eng.state.task.active_monitor == 2
    assert eng.state.task.verified_facts.get("monitor") == 2
    print("OK verified context rules")


def test_other_monitor_context():
    eng = _eng()
    eng.state.task.active_application = "Chrome"
    eng.state.task.active_monitor = 2
    eng.state.task.at = __import__("time").time()
    eng.state.task.verified_facts["monitor"] = 2
    eng.state.task.verified_facts["last_move_monitor"] = 2
    u = eng.understand("Put Spotify on the other monitor.")
    # Should be move family or follow-up with other monitor preserved
    assert "other" in u.rewritten_command.lower() or "monitor" in u.rewritten_command.lower()
    print("OK other monitor", u.rewritten_command)


def test_routing_parity():
    global ROUTING_CONTEXT_MISMATCH_COUNT
    eng = _eng()
    scenarios = [
        "open chrome",
        "mute",
        "volume up",
    ]
    # Seed context for follow-ups
    eng.apply_verified(action="open_app", args={"name": "Chrome"}, status="SUCCESS")
    eng.apply_verified(
        action="move_window_to_monitor",
        args={"name": "Chrome", "monitor": 2},
        status="SUCCESS",
    )
    scenarios += [
        "move it to monitor 2",
        "search Blender",
    ]
    eng.apply_verified(action="search", args={"query": "Blender"}, status="SUCCESS")
    scenarios.append("play the first one")

    mismatches = 0
    for s in scenarios:
        r = routing_parity_check(s)
        mismatches += int(r["mismatch"])
        print(f"  parity {s!r} route={r['route']} mismatch={r['mismatch']}")
    ROUTING_CONTEXT_MISMATCH_COUNT = mismatches
    assert ROUTING_CONTEXT_MISMATCH_COUNT == 0, f"mismatches={ROUTING_CONTEXT_MISMATCH_COUNT}"
    print("OK routing parity ROUTING_CONTEXT_MISMATCH_COUNT=0")


def test_stale_element_no_random():
    eng = _eng()
    from neuron.v4.context.types import EntityReference
    import time

    eng.state.last_referenced = EntityReference(
        entity_type="ui",
        value="ancient",
        world_ref="el_old",
        at=time.time() - 9999,
    )
    u = eng.understand("click it")
    assert u.route is RouteDest.CLARIFY or u.confidence < 0.55 or u.clarification
    print("OK stale referent clarify")


def main():
    global ROUTING_CONTEXT_MISMATCH_COUNT
    test_normalize_variants()
    test_negation()
    test_correction_one_utterance()
    test_compound()
    test_multi_turn_continuity()
    test_result_set_and_stale()
    test_correction_preserves_progress()
    test_clarification_flow()
    test_confirmation_separate()
    test_verified_context_rules()
    test_other_monitor_context()
    test_routing_parity()
    test_stale_element_no_random()
    print(f"\nROUTING_CONTEXT_MISMATCH_COUNT={ROUTING_CONTEXT_MISMATCH_COUNT}")
    print("PASS context scenarios")


if __name__ == "__main__":
    main()
