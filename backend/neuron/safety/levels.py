"""Phase 8 — permission tiers for NEURON actions.

Tiers
  safe      — run immediately (open Chrome, switch window, scroll, …)
  confirm   — ask the user first (send message, upload, modify a file, …)
  high      — high consequence; confirm AND extra scrutiny (privileged shell, …)
  blocked   — never run, even if the user says confirm
              (shutdown/restart, format disk, wipe system, financial sends, …)

Risk aliases from the catalog: low→safe, medium→confirm, high→high, confirm→confirm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Tier names
# ---------------------------------------------------------------------------

SAFE = "safe"
CONFIRM = "confirm"
HIGH = "high"
BLOCKED = "blocked"

_ALIAS = {
    "low": SAFE,
    "safe": SAFE,
    "medium": CONFIRM,  # write-ish / interactive defaults to confirm
    "confirm": CONFIRM,
    "high": HIGH,
    "blocked": BLOCKED,
    "forbid": BLOCKED,
    "forbidden": BLOCKED,
}


def normalize_tier(raw: str | None) -> str:
    return _ALIAS.get((raw or "").strip().lower(), CONFIRM)


# ---------------------------------------------------------------------------
# Catalog defaults by tier (overrides / supplements DEFAULT_RISK)
# ---------------------------------------------------------------------------

# Always safe — perception, navigation, playback, focus
SAFE_TOOLS = {
    "open_app", "open_website", "search_site", "search_web",
    "focus_app", "get_running_apps", "get_windows", "get_active_window",
    "get_monitors", "get_windows_by_monitor", "move_window", "move_window_to_monitor",
    "minimize_app", "maximize_app", "resize_window",
    "scroll", "page_scroll", "move_mouse", "volume", "media",
    "screenshot", "describe_screen", "capture_screen", "capture_monitor",
    "get_cursor_position", "get_active_window_screenshot",
    "ocr_image", "detect_text_regions", "ocr_screen",
    "analyze_screen", "get_screen_context",
    "get_ui_tree", "get_active_window_elements", "find_ui_element", "find_element",
    "get_element_text", "get_element_bounds",
    "play_result", "youtube_home", "youtube_home_play", "play_by_title",
    "list_visible_videos", "skip_ad", "fullscreen", "miniplayer",
    "player_key", "ensure_playback",
    "browser_open", "browser_navigate", "browser_search", "browser_get_page",
    "browser_read_page", "browser_get_elements", "browser_find_element",
    "browser_scroll", "browser_back", "browser_forward",
    "browser_get_tabs", "browser_switch_tab", "browser_research",
    "open_folder", "open_file", "search_files",
    "learn_app", "train_pc", "training_status", "stop_training",
    "wait", "system_report", "web_search_summarize",
    "youtube.search", "youtube.play_result", "youtube.home", "youtube.play_by_title",
    "youtube.list_videos", "youtube.skip_ad", "youtube.fullscreen",
    "youtube.ensure_playback", "youtube.open_channel_videos", "youtube.play_search",
    "youtube_search", "youtube_play_result", "youtube_home", "youtube_play_search",
    "youtube_fullscreen", "youtube_skip_ad",
    "browser.open_tab", "browser.navigate", "browser.search", "browser.get_tabs",
    "browser_open_tab",
    "windows.focus_app", "windows.open_app", "windows.move_to_monitor",
    "windows.get_monitors", "windows.maximize", "windows.minimize",
    "windows_focus_app", "windows_move_to_monitor",
    "spotify.open", "spotify.play", "spotify.pause", "spotify.next",
    "spotify.previous", "spotify.search", "spotify_play", "spotify_pause",
    "files.find", "files.open", "files.open_folder", "files_find", "files_open",
    "blender.open", "blender.focus", "blender.open_project", "blender_open_project",
    "discord.open", "discord.friends", "discord.open_channel", "discord_open_channel",
}

# Needs spoken confirmation before running (content heuristics can also elevate)
CONFIRM_TOOLS = {
    "type_text",
    "create_file", "create_folder",
    "computer_use",
    "close_app", "windows.close_app",
    "replay_clicks",
    "steam_select_account",
    "browser_type",
    "run_shell", "run_powershell",  # also HIGH; listed for clarity
}

# High consequence — confirm + never auto; content may upgrade to blocked
HIGH_TOOLS = {
    "run_shell", "run_powershell",
}

# Interactive but usually OK — elevate via content (Send / Delete / Upload / …)
# press_keys, click*, browser_click, hotkey, window, open_settings, steam_goto


# ---------------------------------------------------------------------------
# Content heuristics (args / goals)
# ---------------------------------------------------------------------------

# Hard block — never execute, even with confirm=True
_BLOCKED_CONTENT = re.compile(
    r"(?i)("
    r"\b(shut\s*down|restart|reboot|power\s*off)\b.{0,40}\b(computer|pc|system|machine|windows)\b"
    r"|\b(format|wipe|erase)\s+([a-z]:\s*|disk|drive|volume|ssd|hdd)\b"
    r"|\brm\s+-rf\s+[\\/]"
    r"|\bdel\s+/[sf]\b"
    r"|\bRemove-Item\b.{0,80}(-Recurse|-Force).{0,40}(Windows|System32|Program Files)"
    r"|\b(Stop-Computer|Restart-Computer|shutdown\s+/[sr])\b"
    r"|\bBitLocker\b"
    r"|\b(net\s+user\s+\w+\s+/add)\b"
    r"|\b(Invoke-Expression|iex)\s*\("
    r"|\bDownloadString\b"
    # Financial irreversible sends
    r"|\b(send|wire|transfer)\s+(\$|USD|EUR|money|funds|bitcoin|btc|eth)\b"
    r"|\b(pay\s+invoice|complete\s+checkout|confirm\s+purchase|buy\s+now)\b"
    r"|\b(venmo|paypal|cashapp|zelle)\s+(send|pay)\b"
    r")",
)

# Needs confirmation (send / upload / modify / install)
_CONFIRM_CONTENT = re.compile(
    r"(?i)("
    r"\b(send|submit|post|tweet|publish|upload|share)\b"
    r"|\b(message|email|dm|direct message|chat)\b.{0,20}\b(send|to)\b"
    r"|\b(modify|overwrite|replace|rename|move|write|save as|edit)\b.{0,40}\b(file|document|folder)\b"
    r"|\b(install|uninstall|update)\b.{0,40}\b(app|application|program|software|package|extension)\b"
    r"|\b(winget|choco|chocolatey|msiexec|pip\s+install|npm\s+install\s+-g)\b"
    r"|\b(delete|remove|erase|trash|recycle)\b"
    r"|\b(password|credential|api[_-]?key|secret|token)\b"
    r")",
)

_HIGH_CONTENT = re.compile(
    r"(?i)("
    r"\b(admin|administrator|elevated|privileged|uac)\b"
    r"|\b(registry|regedit|services\.msc)\b"
    r"|\b(diskpart|bcdedit|sfc\s+/scannow)\b"
    r"|\b(purchase|checkout|payment|credit\s*card|bank\s*account)\b"
    r")",
)

# Read-only PowerShell allowlist (safe without confirm)
_ALLOW_PS = re.compile(
    r"^(Get-|Select-|Write-Output|echo |dir |ls |pwd|whoami|Get-Process|"
    r"Get-Service|Get-ChildItem|Test-Path|Resolve-Path)",
    re.I,
)

_DENY_SHELL = re.compile(
    r"(?i)(\bformat\s+[a-z]:|\brm\s+-rf\b|\bdel\s+/[sf]\b|\bRemove-Item\b.*(-Recurse|-Force)|"
    r"\bshutdown\b|\bRestart-Computer\b|\bStop-Computer\b|\bInvoke-Expression\s*\(|"
    r"\biex\s*\(|DownloadString|BitLocker|\bnet\s+user\s+\w+\s+/add\b)",
)


@dataclass
class Classification:
    tier: str
    reason: str = ""
    tool: str = ""
    content_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "reason": self.reason,
            "tool": self.tool,
            "content_hit": self.content_hit,
        }


def _blob(args: dict | None) -> str:
    args = args or {}
    parts = []
    for key in (
        "command", "goal", "text", "keys", "name", "path", "file",
        "query", "url", "site", "message", "content", "action",
    ):
        val = args.get(key)
        if val not in (None, ""):
            parts.append(str(val))
    return " ".join(parts)


def catalog_tier(name: str) -> str:
    """Tier from explicit sets, else DEFAULT_RISK."""
    n = (name or "").strip()
    if not n:
        return CONFIRM
    dotted = n.replace("_", ".", 1) if ("_" in n and "." not in n) else n
    unders = n.replace(".", "_")

    for cand in (n, dotted, unders):
        if cand in SAFE_TOOLS:
            return SAFE
        if cand in CONFIRM_TOOLS:
            return CONFIRM
        if cand in HIGH_TOOLS:
            return HIGH

    try:
        from neuron.catalog import DEFAULT_RISK
        raw = DEFAULT_RISK.get(n) or DEFAULT_RISK.get(dotted) or DEFAULT_RISK.get(unders)
        if raw:
            return normalize_tier(raw)
    except Exception:
        pass
    return CONFIRM


def classify(name: str, args: dict | None = None) -> Classification:
    """Return the effective permission tier for a tool call."""
    args = args or {}
    tool = (name or "").strip()
    blob = _blob(args)
    base = catalog_tier(tool)

    # Registry risk can raise the floor. Explicit registry SAFE may also
    # lower an unknown-catalog default of confirm (so registered safe tools run).
    # Stale medium→confirm must not override tools explicitly listed as SAFE
    # in the catalog.
    try:
        from neuron.brain import tool_registry
        spec = tool_registry.get(tool)
        if spec and spec.risk:
            reg = normalize_tier(spec.risk)
            if reg == SAFE:
                base = SAFE
            elif base == SAFE and reg == CONFIRM:
                pass
            else:
                base = _max_tier(base, reg)
    except Exception:
        pass

    # Shell deny → blocked
    if tool in ("run_shell", "run_powershell"):
        cmd = str(args.get("command") or "")
        if _DENY_SHELL.search(cmd) or _BLOCKED_CONTENT.search(cmd):
            return Classification(BLOCKED, f"Blocked dangerous command: {cmd[:100]}", tool, True)
        if tool == "run_powershell" and _ALLOW_PS.search(cmd.strip()):
            return Classification(SAFE, "Read-only PowerShell allowlist", tool, False)
        return Classification(HIGH, "Privileged shell requires confirmation", tool, False)

    if blob and _BLOCKED_CONTENT.search(blob):
        return Classification(
            BLOCKED,
            "Blocked high-consequence / irreversible action (shutdown, wipe, financial send, …)",
            tool,
            True,
        )

    if blob and _HIGH_CONTENT.search(blob):
        return Classification(
            _max_tier(base, HIGH),
            "High-consequence content detected — confirmation required",
            tool,
            True,
        )

    if blob and _CONFIRM_CONTENT.search(blob):
        return Classification(
            _max_tier(base, CONFIRM),
            "Needs confirmation (send / upload / modify / install / delete wording)",
            tool,
            True,
        )

    # Window close → confirm
    if tool == "window":
        act = str(args.get("action") or "").lower()
        if act in ("close", "kill"):
            return Classification(CONFIRM, "Closing a window needs confirmation", tool, True)

    # Click / type targets that look like Send / Delete / Upload
    if tool in (
        "click_text", "click_element", "click_ui_element", "browser_click",
        "press_keys", "hotkey", "computer_use",
    ):
        label = str(
            args.get("name") or args.get("text") or args.get("goal")
            or args.get("keys") or args.get("query") or ""
        )
        if label and _CONFIRM_CONTENT.search(label):
            return Classification(
                CONFIRM,
                f"UI action looks consequential ({label[:60]}) — confirmation required",
                tool,
                True,
            )
        if label and _BLOCKED_CONTENT.search(label):
            return Classification(BLOCKED, "Blocked high-consequence UI action", tool, True)

    return Classification(base, f"Catalog tier={base}", tool, False)


_ORDER = {SAFE: 0, CONFIRM: 1, HIGH: 2, BLOCKED: 3}


def _max_tier(a: str, b: str) -> str:
    return a if _ORDER.get(a, 1) >= _ORDER.get(b, 1) else b


def tier_prompt() -> str:
    return (
        "SAFETY TIERS (Phase 8):\n"
        "- safe: open apps/sites, focus/switch windows, scroll, YouTube, screenshots — run now.\n"
        "- confirm: send/upload/modify files, type/click that sends, create files, close apps "
        "— ask user; wait for 'confirm' / 'yes' / 'go ahead'.\n"
        "- high: shell / privileged commands — confirm + scrutiny.\n"
        "- blocked: shutdown/restart, format/wipe disk, system deletes, financial sends — NEVER run.\n"
        "PyAutoGUI FAILSAFE stays on (mouse to any screen corner aborts). "
        "Say 'Neuron, stop' to interrupt speech or a running task."
    )
