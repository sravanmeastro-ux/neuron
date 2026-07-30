"""Domain skill workflows — compose existing tools into stable APIs.

Example:
  from neuron.skills import youtube, windows, browser, spotify, discord, files, blender
  youtube.search("MrBeast")
  windows.move_to_monitor("chrome", 2)

Skills are thin workflows over browser / windows / actions — not a second OS layer.
"""

from __future__ import annotations

from neuron.skills import blender, browser, discord, files, spotify, windows, youtube
from neuron.skills.registry import SKILL_SPECS, bootstrap_skills, skill_prompt

__all__ = [
    "youtube",
    "browser",
    "windows",
    "spotify",
    "discord",
    "files",
    "blender",
    "bootstrap_skills",
    "skill_prompt",
    "SKILL_SPECS",
]
