"""Hard failsafe protections that always stay on.

- PyAutoGUI FAILSAFE: slam mouse into any screen corner → raises FailSafeException
- OS power actions (shutdown / restart) remain disabled in the brain
"""

from __future__ import annotations


def ensure_failsafe() -> str:
    """Enable PyAutoGUI emergency corner failsafe. Call at process start."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        # Slightly slower default pause reduces runaway click storms
        if getattr(pyautogui, "PAUSE", 0) < 0.05:
            pyautogui.PAUSE = 0.05
        return "PyAutoGUI FAILSAFE on (move mouse to a screen corner to abort)."
    except Exception as exc:
        return f"FAILSAFE unavailable: {exc}"


def power_actions_disabled_message() -> str:
    return "Shutdown and restart are disabled for safety. Do it manually."
