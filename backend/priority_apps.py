"""Priority app playbooks — Discord, YouTube, Google, Opera, Settings,
Steam, Blender, Notepad, WhatsApp.

These are NOT "record every click forever". They are curated how-to maps:
voice phrases, deep links, UI click targets, and workflows NEURON should use.
install_builtins() writes them into app_memory/ so the planner always has them.
train_live() optionally opens each app once and deep-scans the real UI.
"""

from __future__ import annotations

import time
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parent / "app_memory"

# Curated knowledge — preferred over guessing / random pixel clicks.
PRIORITY: dict[str, dict] = {
    "discord": {
        "kind": "desktop_app",
        "name": "Discord",
        "summary": (
            "Discord desktop chat. Friends/DMs live at discord://-/channels/@me. "
            "Use discord_friends for 'friends chat'; open_app for the client."
        ),
        "preferred_action": "discord_friends",
        "deep_links": {
            "friends": "discord://-/channels/@me",
            "dms": "discord://-/channels/@me",
            "activity": "discord://-/activity",
            "library": "discord://-/library",
        },
        "notes": (
            "NEVER treat Discord as a website in controlled Chrome for Friends. "
            "Friends chat → discord_friends. Server channels → computer_use or "
            "click_text after focusing Discord. Ctrl+K = Quick Switcher."
        ),
        "click_targets": [
            {"label": "Friends", "where": "left rail / home", "do": "discord_friends"},
            {"label": "Direct Messages", "where": "Friends home", "do": "discord_friends"},
            {"label": "User Settings", "where": "bottom-left gear", "keys": "ctrl+,"},
            {"label": "Quick Switcher", "where": "anywhere", "keys": "ctrl+k"},
            {"label": "Mute", "where": "voice panel", "keys": "ctrl+shift+m"},
            {"label": "Deafen", "where": "voice panel", "keys": "ctrl+shift+d"},
            {"label": "Search", "where": "toolbar", "keys": "ctrl+f"},
        ],
        "voice_commands": [
            {"say": "open discord", "do": "open_app discord"},
            {"say": "open friends chat", "do": "discord_friends"},
            {"say": "open discord friends", "do": "discord_friends"},
            {"say": "open dms", "do": "discord_friends"},
            {"say": "open discord settings", "do": "open_app discord; press_keys control+comma"},
            {"say": "discord quick switcher", "do": "press_keys control k"},
        ],
        "navigation": [
            {"label": "Friends / DMs", "how": "discord_friends"},
            {"label": "Quick Switcher", "how": "press_keys control k"},
            {"label": "User Settings", "how": "press_keys control+comma"},
        ],
        "workflows": [
            {
                "say": "message a friend",
                "steps": [
                    "discord_friends",
                    "computer_use: click the friend name then type the message",
                ],
            }
        ],
    },
    "youtube": {
        "kind": "website",
        "name": "YouTube",
        "summary": "YouTube in NEURON controlled browser — never open_app / Windows Search.",
        "preferred_action": "open_website",
        "notes": (
            "Use open_website youtube, search_site, youtube_home, youtube_home_play, "
            "play_result, play_by_title, skip_ad, ensure_playback, fullscreen, "
            "page_scroll, player_key, list_visible_videos."
        ),
        "click_targets": [
            {"label": "Home", "where": "left rail", "do": "youtube_home"},
            {"label": "Search", "where": "top bar", "do": "search_site youtube"},
            {"label": "Skip Ad", "where": "player", "do": "skip_ad"},
            {"label": "Fullscreen", "where": "player", "do": "fullscreen / key f"},
            {"label": "Mute", "where": "player", "do": "player_key m"},
            {"label": "Play/Pause", "where": "player", "do": "ensure_playback / key k"},
            {"label": "Miniplayer", "where": "player", "do": "miniplayer / key i"},
            {"label": "Nth video tile", "where": "feed viewport", "do": "play_result / youtube_home_play"},
        ],
        "voice_commands": [
            {"say": "open youtube", "do": "open_website youtube"},
            {"say": "search X on youtube", "do": "search_site youtube X"},
            {"say": "come back to youtube home", "do": "youtube_home"},
            {"say": "play the 2nd video on homepage", "do": "youtube_home_play 2"},
            {"say": "play the 2nd video on screen", "do": "play_result 2"},
            {"say": "play the video called X", "do": "play_by_title X"},
            {"say": "skip the ad", "do": "skip_ad"},
            {"say": "pause the video", "do": "ensure_playback pause"},
            {"say": "fullscreen", "do": "fullscreen"},
            {"say": "scroll down", "do": "page_scroll down"},
            {"say": "how many videos on screen", "do": "list_visible_videos"},
            {"say": "mute youtube", "do": "player_key m"},
            {"say": "next video", "do": "player_key Shift+N"},
        ],
        "navigation": [
            {"label": "Home", "how": "youtube_home / open_website youtube"},
            {"label": "Search", "how": "search_site youtube <query>"},
            {"label": "Skip Ad", "how": "skip_ad"},
        ],
    },
    "google": {
        "kind": "website",
        "name": "Google",
        "summary": "Google Search / web — open_website google or search_site / search_web.",
        "preferred_action": "search_site",
        "notes": (
            "Google is a WEBSITE. 'search X on google' → search_site google X "
            "or search_web. Gmail/Drive/Maps are separate sites."
        ),
        "click_targets": [
            {"label": "Search box", "where": "center / top", "do": "search_site google"},
            {"label": "I'm Feeling Lucky", "where": "home", "do": "computer_use if needed"},
            {"label": "Images", "where": "top tabs", "do": "open_website google.com/imghp"},
            {"label": "Maps", "where": "apps", "do": "open_website maps"},
            {"label": "Gmail", "where": "apps", "do": "open_website gmail"},
        ],
        "voice_commands": [
            {"say": "open google", "do": "open_website google"},
            {"say": "search X on google", "do": "search_site google X"},
            {"say": "google X", "do": "search_site google X"},
            {"say": "open gmail", "do": "open_website gmail"},
            {"say": "open google maps", "do": "open_website maps"},
            {"say": "open google drive", "do": "open_website drive"},
        ],
        "navigation": [
            {"label": "Search", "how": "search_site google <query>"},
            {"label": "Gmail", "how": "open_website gmail"},
            {"label": "Maps", "how": "open_website maps"},
            {"label": "Drive", "how": "open_website drive"},
        ],
    },
    "opera": {
        "kind": "browser",
        "name": "Opera",
        "summary": "Opera desktop browser. Prefer open_app opera; sites still use open_website when possible.",
        "preferred_action": "open_app",
        "notes": (
            "Opening Opera itself → open_app opera. Opening a site in controlled Chrome "
            "is still fine for YouTube automation. For Opera-only UI use computer_use."
        ),
        "click_targets": [
            {"label": "Address bar", "where": "top", "keys": "ctrl+l"},
            {"label": "New tab", "where": "tab strip", "keys": "ctrl+t"},
            {"label": "Close tab", "where": "tab", "keys": "ctrl+w"},
            {"label": "Reopen tab", "where": "anywhere", "keys": "ctrl+shift+t"},
            {"label": "Find", "where": "page", "keys": "ctrl+f"},
            {"label": "Sidebar", "where": "left", "do": "computer_use click sidebar icon"},
            {"label": "Settings", "where": "menu", "keys": "alt+p"},
        ],
        "voice_commands": [
            {"say": "open opera", "do": "open_app opera"},
            {"say": "new tab in opera", "do": "open_app opera; press_keys control t"},
            {"say": "close tab", "do": "press_keys control w"},
            {"say": "opera address bar", "do": "press_keys control l"},
            {"say": "opera settings", "do": "press_keys alt p"},
        ],
        "navigation": [
            {"label": "New tab", "how": "press_keys control t"},
            {"label": "Address bar", "how": "press_keys control l"},
            {"label": "Settings", "how": "press_keys alt p"},
        ],
    },
    "windows-settings": {
        "kind": "system",
        "name": "Windows Settings",
        "summary": "Windows Settings via ms-settings: URIs — never click Start→Settings blindly.",
        "preferred_action": "open_settings",
        "deep_links": {
            "home": "ms-settings:",
            "system": "ms-settings:system",
            "display": "ms-settings:display",
            "sound": "ms-settings:sound",
            "notifications": "ms-settings:notifications",
            "bluetooth": "ms-settings:bluetooth",
            "wifi": "ms-settings:network-wifi",
            "network": "ms-settings:network",
            "personalization": "ms-settings:personalization",
            "apps": "ms-settings:appsfeatures",
            "privacy": "ms-settings:privacy",
            "accounts": "ms-settings:accounts",
            "time": "ms-settings:dateandtime",
            "update": "ms-settings:windowsupdate",
            "gaming": "ms-settings:gaming-gamebar",
            "storage": "ms-settings:storagesense",
        },
        "notes": (
            "Use open_settings {page}. Examples: bluetooth, wifi, display, sound, update. "
            "open_app settings opens the Settings home."
        ),
        "click_targets": [
            {"label": "System", "where": "home list", "do": "open_settings system"},
            {"label": "Bluetooth & devices", "where": "home", "do": "open_settings bluetooth"},
            {"label": "Network & internet", "where": "home", "do": "open_settings network"},
            {"label": "Personalization", "where": "home", "do": "open_settings personalization"},
            {"label": "Apps", "where": "home", "do": "open_settings apps"},
            {"label": "Windows Update", "where": "home", "do": "open_settings update"},
            {"label": "Display", "where": "System", "do": "open_settings display"},
            {"label": "Sound", "where": "System", "do": "open_settings sound"},
        ],
        "voice_commands": [
            {"say": "open settings", "do": "open_settings home"},
            {"say": "open windows settings", "do": "open_settings home"},
            {"say": "open bluetooth settings", "do": "open_settings bluetooth"},
            {"say": "open wifi settings", "do": "open_settings wifi"},
            {"say": "open display settings", "do": "open_settings display"},
            {"say": "open sound settings", "do": "open_settings sound"},
            {"say": "open windows update", "do": "open_settings update"},
            {"say": "open personalization settings", "do": "open_settings personalization"},
        ],
        "navigation": [
            {"label": "Bluetooth", "how": "open_settings bluetooth"},
            {"label": "Wi‑Fi", "how": "open_settings wifi"},
            {"label": "Display", "how": "open_settings display"},
            {"label": "Update", "how": "open_settings update"},
        ],
    },
    "steam": {
        "kind": "desktop_app",
        "name": "Steam",
        "summary": "Steam desktop client — steam_goto / steam_select_account / steam:// links only.",
        "preferred_action": "steam_goto",
        "deep_links": {
            "library": "steam://open/games",
            "store": "steam://open/store",
            "friends": "steam://open/friends",
            "downloads": "steam://open/downloads",
            "community": "steam://open/community",
            "settings": "steam://open/settings",
            "news": "steam://open/news",
        },
        "notes": (
            "Always steam_goto / steam_select_account. Never browser or Windows Search. "
            "Top tabs: STORE, LIBRARY, COMMUNITY. Friends & Chat is separate."
        ),
        "click_targets": [
            {"label": "STORE", "where": "top nav", "do": "steam_goto store"},
            {"label": "LIBRARY", "where": "top nav", "do": "steam_goto library"},
            {"label": "COMMUNITY", "where": "top nav", "do": "steam_goto community"},
            {"label": "Friends & Chat", "where": "friends", "do": "steam_goto friends"},
            {"label": "Downloads", "where": "bottom / menu", "do": "steam_goto downloads"},
            {"label": "Settings", "where": "Steam menu", "do": "steam_goto settings"},
            {"label": "Account tile", "where": "Who's playing", "do": "steam_select_account"},
        ],
        "voice_commands": [
            {"say": "open steam", "do": "open_app steam"},
            {"say": "open steam library", "do": "steam_goto library"},
            {"say": "open steam store", "do": "steam_goto store"},
            {"say": "open steam friends", "do": "steam_goto friends"},
            {"say": "open steam downloads", "do": "steam_goto downloads"},
            {"say": "open steam settings", "do": "steam_goto settings"},
            {"say": "login to the first steam account", "do": "steam_select_account 1"},
            {"say": "scroll down", "do": "scroll down in steam"},
        ],
        "navigation": [
            {"label": "Library", "how": "steam_goto library"},
            {"label": "Store", "how": "steam_goto store"},
            {"label": "Community", "how": "steam_goto community"},
            {"label": "Friends", "how": "steam_goto friends"},
            {"label": "Downloads", "how": "steam_goto downloads"},
        ],
    },
    "blender": {
        "kind": "desktop_app",
        "name": "Blender",
        "summary": "Blender 3D. Heavy UI — prefer shortcuts + computer_use for toolbar clicks.",
        "preferred_action": "open_app",
        "notes": (
            "open_app blender. Layouts: Layout, Modeling, Sculpting, UV Editing, "
            "Shading, Animation, Rendering, Geometry Nodes, Scripting. "
            "Spacebar = search operator. Prefer press_keys / computer_use over guessing menus."
        ),
        "click_targets": [
            {"label": "Layout workspace", "where": "top tabs", "do": "computer_use click Layout"},
            {"label": "Modeling", "where": "top tabs", "do": "computer_use click Modeling"},
            {"label": "Shading", "where": "top tabs", "do": "computer_use click Shading"},
            {"label": "Render", "where": "top / F12", "keys": "f12"},
            {"label": "Search", "where": "anywhere", "keys": "f3"},
            {"label": "Save", "where": "file", "keys": "ctrl+s"},
            {"label": "Undo", "where": "anywhere", "keys": "ctrl+z"},
            {"label": "Viewport shade solid", "where": "viewport header", "do": "computer_use"},
            {"label": "Add mesh", "where": "Add menu", "keys": "shift+a"},
        ],
        "voice_commands": [
            {"say": "open blender", "do": "open_app blender"},
            {"say": "blender search", "do": "press_keys f3"},
            {"say": "render in blender", "do": "press_keys f12"},
            {"say": "save blender file", "do": "press_keys control s"},
            {"say": "add object in blender", "do": "press_keys shift a"},
            {"say": "undo in blender", "do": "press_keys control z"},
        ],
        "navigation": [
            {"label": "Operator search", "how": "press_keys f3"},
            {"label": "Render", "how": "press_keys f12"},
            {"label": "Add", "how": "press_keys shift a"},
            {"label": "Save", "how": "press_keys control s"},
        ],
        "workflows": [
            {
                "say": "switch to modeling workspace",
                "steps": ["open_app blender", "computer_use: click the Modeling tab at the top"],
            }
        ],
    },
    "notepad": {
        "kind": "desktop_app",
        "name": "Notepad",
        "summary": "Classic Notepad — open, type, save with Ctrl+S.",
        "preferred_action": "open_app",
        "notes": "open_app notepad → type_text → press_keys control s. New window: control n.",
        "click_targets": [
            {"label": "File", "where": "menu", "keys": "alt+f"},
            {"label": "Edit", "where": "menu", "keys": "alt+e"},
            {"label": "Save", "where": "File", "keys": "ctrl+s"},
            {"label": "Save As", "where": "File", "keys": "ctrl+shift+s"},
            {"label": "New", "where": "File", "keys": "ctrl+n"},
            {"label": "Open", "where": "File", "keys": "ctrl+o"},
            {"label": "Find", "where": "Edit", "keys": "ctrl+f"},
            {"label": "Select all", "where": "Edit", "keys": "ctrl+a"},
        ],
        "voice_commands": [
            {"say": "open notepad", "do": "open_app notepad"},
            {"say": "type in notepad", "do": "open_app notepad; type_text"},
            {"say": "save notepad", "do": "press_keys control s"},
            {"say": "new notepad", "do": "press_keys control n"},
            {"say": "select all in notepad", "do": "press_keys control a"},
        ],
        "navigation": [
            {"label": "Save", "how": "press_keys control s"},
            {"label": "New", "how": "press_keys control n"},
            {"label": "Open", "how": "press_keys control o"},
        ],
        "workflows": [
            {
                "say": "write a note",
                "steps": ["open_app notepad", "wait 1", "type_text", "press_keys control s"],
            }
        ],
    },
    "whatsapp": {
        "kind": "desktop_app",
        "name": "WhatsApp",
        "summary": "WhatsApp Desktop. Chat list left, conversation right. Ctrl+F search.",
        "preferred_action": "open_app",
        "notes": (
            "open_app whatsapp. Search chats Ctrl+F / Ctrl+Shift+F. "
            "New chat: computer_use click New chat. "
            "Sending a message to someone: open WhatsApp → search name → click chat → type_text → Enter."
        ),
        "click_targets": [
            {"label": "Search or start new chat", "where": "top-left", "keys": "ctrl+f"},
            {"label": "New chat", "where": "toolbar", "do": "computer_use click New chat"},
            {"label": "Chat list item", "where": "left list", "do": "computer_use click contact name"},
            {"label": "Message box", "where": "bottom", "do": "type_text then enter"},
            {"label": "Attach", "where": "message bar", "do": "computer_use click attach"},
            {"label": "Settings", "where": "menu", "do": "computer_use open settings"},
            {"label": "Status", "where": "left rail", "do": "computer_use click Status"},
            {"label": "Calls", "where": "left rail", "do": "computer_use click Calls"},
        ],
        "voice_commands": [
            {"say": "open whatsapp", "do": "open_app whatsapp"},
            {"say": "search in whatsapp", "do": "press_keys control f"},
            {"say": "new whatsapp chat", "do": "computer_use open new chat in WhatsApp"},
            {"say": "message someone on whatsapp", "do": "computer_use find contact and open chat"},
        ],
        "navigation": [
            {"label": "Search chats", "how": "press_keys control f"},
            {"label": "New chat", "how": "computer_use click New chat"},
            {"label": "Send message", "how": "type_text then press_keys enter"},
        ],
        "workflows": [
            {
                "say": "message a contact",
                "steps": [
                    "open_app whatsapp",
                    "press_keys control f",
                    "type_text <name>",
                    "computer_use: open the chat and type the message",
                ],
            }
        ],
    },
}

# Alias map so learn_app("settings") finds windows-settings, etc.
ALIASES = {
    "settings": "windows-settings",
    "windows settings": "windows-settings",
    "win settings": "windows-settings",
    "yt": "youtube",
    "google search": "google",
    "google chrome": "chrome",  # not priority pack; ignore if missing
}


def install_builtins(force: bool = True) -> str:
    """Write priority playbooks into app_memory/ (no UI spam)."""
    import app_learner

    saved = []
    for slug, data in PRIORITY.items():
        payload = dict(data)
        payload["learned_from"] = "priority_builtins"
        payload["slug"] = slug
        if force or not app_learner.load(slug):
            app_learner.save(slug, payload)
            saved.append(slug)
        # Also refresh known shortcuts merge target
    # Mirror steam/youtube/notepad into KNOWN path already covered by PRIORITY
    return (
        f"Installed playbooks for {len(saved)} apps: {', '.join(saved)}. "
        f"Voice maps + click targets ready (Discord, YouTube, Google, Opera, "
        f"Windows Settings, Steam, Blender, Notepad, WhatsApp)."
    )


def seed_voice_recipes() -> int:
    """Push high-value phrases into voice_recipes store."""
    import voice_recipes

    pairs = [
        ("open friends chat", "discord_friends", {}),
        ("open discord", "open_app", {"name": "discord"}),
        ("open youtube", "open_website", {"site": "youtube"}),
        ("open google", "open_website", {"site": "google"}),
        ("open opera", "open_app", {"name": "opera"}),
        ("open blender", "open_app", {"name": "blender"}),
        ("open notepad", "open_app", {"name": "notepad"}),
        ("open whatsapp", "open_app", {"name": "whatsapp"}),
        ("open steam", "open_app", {"name": "steam"}),
        ("open steam library", "steam_goto", {"section": "library"}),
        ("open steam friends", "steam_goto", {"section": "friends"}),
        ("open windows settings", "open_settings", {"page": "home"}),
        ("open settings", "open_settings", {"page": "home"}),
        ("open bluetooth settings", "open_settings", {"page": "bluetooth"}),
        ("open wifi settings", "open_settings", {"page": "wifi"}),
        ("open display settings", "open_settings", {"page": "display"}),
        ("open sound settings", "open_settings", {"page": "sound"}),
        ("search on google", "search_site", {"site": "google", "query": ""}),
    ]
    n = 0
    for say, action, args in pairs:
        voice_recipes.remember(say, action, args)
        n += 1
    return n


def train_live(apps: list[str] | None = None, settle: float = 2.0) -> str:
    """Open each priority desktop app once, deep-learn UI, keep builtins merged."""
    import app_learner

    order = apps or [
        "notepad",
        "windows-settings",
        "steam",
        "discord",
        "whatsapp",
        "opera",
        "blender",
        # websites learned without open_app spam
        "youtube",
        "google",
    ]
    install_builtins(force=True)
    seed_voice_recipes()
    results = []
    for key in order:
        slug = ALIASES.get(key, key)
        data = PRIORITY.get(slug)
        if not data:
            results.append(f"{key}: unknown")
            continue
        kind = data.get("kind")
        try:
            if kind == "website":
                msg = app_learner.learn_website(
                    "youtube" if slug == "youtube" else slug,
                    force=True,
                )
                results.append(f"{slug}: {msg}")
                continue
            if kind == "system":
                # Settings: open home then learn
                import actions
                actions.open_settings("home")
                time.sleep(settle)
                msg = app_learner.learn_app("settings", force=True, open_if_needed=False)
                results.append(f"{slug}: {msg or 'saved'}")
                # Re-merge builtins over junk scans
                install_builtins(force=True)
                continue
            # Desktop apps — learn_app opens them
            target = "settings" if slug == "windows-settings" else slug
            msg = app_learner.learn_app(target, force=True, open_if_needed=True)
            results.append(f"{slug}: {msg or 'saved'}")
            time.sleep(0.4)
        except Exception as exc:
            results.append(f"{slug}: FAILED {exc}")
            # Keep builtin anyway
            app_learner.save(slug, dict(data) | {"learned_from": "priority_builtins_after_fail"})
    install_builtins(force=True)
    return "Priority train done:\n- " + "\n- ".join(results)


def for_prompt(hint: str = "") -> str:
    h = (hint or "").lower()
    lines = ["PRIORITY APP CLICK MAPS (prefer tools / these targets over guessing):"]
    for slug, data in PRIORITY.items():
        if h and slug not in h and data.get("name", "").lower() not in h:
            # Still include if any alias word present
            if not any(tok in h for tok in slug.replace("-", " ").split()):
                continue
        clicks = data.get("click_targets") or []
        if not clicks:
            continue
        bit = "; ".join(
            f"{c.get('label')}→{c.get('do') or c.get('keys')}" for c in clicks[:8]
        )
        lines.append(f"- {data.get('name') or slug}: {bit}")
    if len(lines) == 1:
        # No hint match — short index
        lines.append(
            "- Apps trained: Discord, YouTube, Google, Opera, Windows Settings, "
            "Steam, Blender, Notepad, WhatsApp (see LEARNED APP MEMORY)."
        )
    return "\n".join(lines)
