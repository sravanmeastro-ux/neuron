"""V4.7 context smoke — MOCK/read-only clarification resume demo."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neuron.v4.context import reset_conversation_engine
from neuron.v4.context.clarify import set_clarification


def main():
    eng = reset_conversation_engine()
    print("V4.7 context smoke (no live control)")
    print()

    # Ambiguous request -> clarification
    eng.set_pending_clarification(
        set_clarification(
            prompt="Which Settings do you mean: the one in Chrome or the one in the app window?",
            original_goal="click Settings",
            options=[
                {"label": "Chrome Settings", "app": "Chrome", "element_id": "el_chrome"},
                {"label": "App Settings", "app": "App", "element_id": "el_app"},
            ],
            source="smoke",
        )
    )
    print("PENDING CLARIFY:", eng.state.pending_clarification.prompt)
    print()

    u = eng.understand("Chrome one")
    print("USER: Chrome one")
    print("CONTINUITY:", u.continuity.value)
    print("RESOLUTION:", u.clarification_resolution)
    print("REWRITTEN:", u.rewritten_command)
    print("ROUTE:", u.route.value)
    assert u.clarification_resolution and u.clarification_resolution.get("resolved")
    assert eng.state.pending_clarification is None

    # Resume as hierarchical-bound goal
    goal = eng.to_plan_goal(u)
    print("PLAN GOAL:", goal.text)
    print()
    print("Context smoke PASS (no live control).")


if __name__ == "__main__":
    main()
