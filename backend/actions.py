"""N.E.U.R.O.N hands — actually controls keyboard, mouse and apps (Windows)."""

import os
import re
import shutil
import subprocess
import time
import webbrowser
import winreg
from datetime import datetime

import pyautogui

# Safety: slam the mouse into any screen corner to abort everything.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.04

SCREEN_W, SCREEN_H = pyautogui.size()

# Apps openable by voice. Values are commands for `start` / executables.
APPS = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "browser": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "calculator": "calc",
    "paint": "mspaint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "command prompt": "cmd",
    "terminal": "wt",
    "cmd": "cmd",
    "settings": "ms-settings:",
    "task manager": "taskmgr",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "spotify": "spotify",
    "steam": "steam",
    "whatsapp": "whatsapp",
    "vs code": "code",
    "code": "code",
    "cursor": "cursor",
}

# Official Steam client deep-links — used as a secondary path.
# Top nav (STORE / LIBRARY / COMMUNITY) is more reliable via UI click.
STEAM_SECTIONS = {
    "library": ["steam://open/games"],
    "games": ["steam://open/games"],
    "store": ["steam://open/store"],
    "community": ["steam://url/CommunityHome", "steam://open/community"],
    "friends": ["steam://open/friends"],
    "friend": ["steam://open/friends"],
    "downloads": ["steam://open/downloads"],
    "download": ["steam://open/downloads"],
    "settings": ["steam://open/settings"],
    "news": ["steam://open/news"],
    "inventory": ["steam://url/SteamInventory"],
    "profile": ["steam://url/SteamIDMyProfile"],
}

# Visible top-nav labels in the Steam client (must match on-screen text).
STEAM_TAB_LABELS = {
    "library": "LIBRARY",
    "games": "LIBRARY",
    "store": "STORE",
    "community": "COMMUNITY",
}

STEAM_VERIFY = {
    "community": ("community supernav", "discussions", "workshop", "market", "broadcasts"),
    "library": ("library supernav", "add a game", "home collections downloads"),
    "games": ("library supernav", "add a game", "home collections downloads"),
    "store": ("store supernav", "discovery queue", "wishlist", "points shop"),
    "friends": ("friends & chat", "add a friend"),
    "friend": ("friends & chat", "add a friend"),
    "downloads": ("manage downloads",),
    "download": ("manage downloads",),
    "settings": ("settings", "in-game", "interface"),
    "news": ("news",),
    "inventory": ("inventory",),
    "profile": ("profile",),
}

KEY_ALIASES = {
    "enter": "enter", "return": "enter",
    "escape": "esc", "esc": "esc",
    "tab": "tab", "space": "space", "spacebar": "space",
    "backspace": "backspace", "delete": "delete",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end",
    "page up": "pageup", "page down": "pagedown",
    "windows": "win", "windows key": "win",
    "control": "ctrl", "shift": "shift", "alt": "alt",
    "f5": "f5", "f11": "f11",
}


# Common web services people mean as WEBSITES, not desktop apps.
WEB_SERVICES = {
    "youtube": "youtube.com",
    "yt": "youtube.com",
    "gmail": "mail.google.com",
    "google": "google.com",
    "maps": "google.com/maps",
    "google maps": "google.com/maps",
    "drive": "drive.google.com",
    "google drive": "drive.google.com",
    "facebook": "facebook.com",
    "fb": "facebook.com",
    "instagram": "instagram.com",
    "insta": "instagram.com",
    "twitter": "twitter.com",
    "reddit": "reddit.com",
    "netflix": "netflix.com",
    "prime video": "primevideo.com",
    "hotstar": "hotstar.com",
    "chatgpt": "chat.openai.com",
    "github": "github.com",
    "linkedin": "linkedin.com",
    "amazon": "amazon.in",
    "flipkart": "flipkart.com",
    "wikipedia": "wikipedia.org",
    "gemini": "gemini.google.com",
}

# Websites that support a search query, and how to build the search URL.
SITE_SEARCH = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "yt": "https://www.youtube.com/results?search_query={q}",
    "google": "https://www.google.com/search?q={q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "google maps": "https://www.google.com/maps/search/{q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "youtube music": "https://music.youtube.com/search?q={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "github": "https://github.com/search?q={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
}

BROWSER_EXES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "brave": "brave",
}


def _resolve_exe(command: str):
    """Find the real executable for a command name, like the Run dialog does."""
    if os.path.isfile(command):
        return command

    found = shutil.which(command)
    if found:
        return found

    # App Paths registry — how Windows resolves 'chrome', 'winword', etc.
    exe_name = command if command.lower().endswith(".exe") else command + ".exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
            with winreg.OpenKey(root, key_path) as key:
                path = winreg.QueryValueEx(key, None)[0].strip('"')
                if os.path.isfile(path):
                    return path
        except OSError:
            pass
    return None


def open_app(name: str, *, auto_learn: bool = True) -> str:
    name = name.strip().lower().strip(" .!?")
    # Websites are NEVER apps — opening them via Start Menu / Win search is wrong.
    if name in WEB_SERVICES or name in ("yt",):
        raise RuntimeError(
            f"'{name}' is a website, not a desktop app. Use open_website / the controlled browser."
        )
    # Never dump whole natural-language commands into Windows Search.
    if _looks_like_command_phrase(name):
        raise RuntimeError(
            f"'{name}' is a command, not an app name. Use a specific tool "
            f"(steam_select_account / steam_goto / computer_use), not open_app."
        )
    target = APPS.get(name, name)

    # URI targets like ms-settings: open directly
    if target.endswith(":"):
        os.startfile(target)
        if auto_learn:
            _schedule_learn_safe(name)
        return f"Opening {name}."

    exe = _resolve_exe(target)
    if exe:
        subprocess.Popen([exe])
        if auto_learn:
            _schedule_learn_safe(name)
        return f"Opening {name}."

    # Short app-name fallback only (Start Menu). Never for long phrases.
    if len(name.split()) <= 3:
        reply = open_from_start_menu(name)
        if auto_learn:
            _schedule_learn_safe(name)
        return reply
    raise RuntimeError(
        f"I don't know an app called '{name}'. Say a short app name like 'steam' or 'notepad'."
    )


def _looks_like_command_phrase(name: str) -> bool:
    """True if this is English intent, not a launchable app title."""
    n = (name or "").strip().lower()
    if not n:
        return True
    words = n.split()
    if len(words) >= 5:
        return True
    traps = (
        "account", "login", "log in", "sign in", "first", "second", "third",
        "1st", "2nd", "3rd", "open the", "click", "select", "search",
        "download", "install", "play the", "in steam", "on youtube",
    )
    return any(t in n for t in traps)


def _schedule_learn_safe(name: str):
    """After opening an app, study how it works in the background."""
    try:
        import app_watch
        app_watch.schedule_learn(name, settle_s=3.0)
    except Exception:
        pass


def open_from_start_menu(name: str) -> str:
    """Last-resort app launch via Start search. ONLY for short app names."""
    if _looks_like_command_phrase(name) or len((name or "").split()) > 3:
        raise RuntimeError(
            f"Refusing Windows Search for '{name}' — that opens Bing, not the app."
        )
    pyautogui.press("win")
    time.sleep(0.7)
    pyautogui.write(name, interval=0.03)
    time.sleep(1.0)  # let search results settle
    pyautogui.press("enter")
    return f"Opening {name}."


def _steam_window():
    """Return the main Steam window or login picker, or None."""
    try:
        import uiautomation as auto
        w = auto.WindowControl(searchDepth=1, Name="Steam")
        if w.Exists(0, 0):
            return w
        # Title may include more text; also catch account picker / login.
        for ch in auto.GetRootControl().GetChildren():
            try:
                if ch.ControlTypeName != "WindowControl":
                    continue
                title = (ch.Name or "").strip()
                low = title.lower()
                if low.startswith("steam") or "who's playing" in low or "who is playing" in low:
                    return ch
            except Exception:
                continue
    except Exception:
        pass
    return None


def _focus_steam() -> bool:
    w = _steam_window()
    if not w:
        open_app("steam", auto_learn=False)
        time.sleep(2.5)
        w = _steam_window()
    if not w:
        return False
    try:
        w.SetActive()
        time.sleep(0.35)
        try:
            import app_context
            app_context.set_app("steam")
        except Exception:
            pass
        return True
    except Exception:
        return False


def _steam_collect_names(budget: int = 120) -> list[str]:
    """Flat list of visible control names under the Steam window."""
    w = _steam_window()
    if not w:
        return []
    out = []
    try:
        stack = [(w, 0)]
        while stack and len(out) < budget:
            ctrl, depth = stack.pop()
            if depth > 10:
                continue
            try:
                kids = ctrl.GetChildren()
            except Exception:
                kids = []
            for ch in kids:
                stack.append((ch, depth + 1))
                try:
                    nm = (ch.Name or "").strip()
                except Exception:
                    nm = ""
                if nm:
                    out.append(nm)
    except Exception:
        pass
    return out


def _steam_verified(section: str) -> bool:
    """True if Steam UI looks like the requested section is open."""
    needles = STEAM_VERIFY.get(section) or ()
    if not needles:
        return False
    blob = " | ".join(_steam_collect_names()).lower()
    # Prefer a distinctive supernav hit when available.
    for n in needles:
        if "supernav" in n and n in blob:
            return True
    hits = sum(1 for n in needles if n in blob)
    need = 1 if section in ("downloads", "download", "settings", "news", "friends", "friend") else 1
    # For main tabs, require either supernav (handled above) or 2 weaker signals.
    if section in ("community", "library", "games", "store"):
        return hits >= 2
    return hits >= need


def _click_steam_tab(label: str) -> bool:
    """Click STORE / LIBRARY / COMMUNITY text in the Steam chrome. Verified path."""
    w = _steam_window()
    if not w:
        return False
    want = (label or "").strip().upper()
    target = None

    def walk(ctrl, depth=0):
        nonlocal target
        if target is not None or depth > 10:
            return
        try:
            kids = ctrl.GetChildren()
        except Exception:
            return
        for ch in kids:
            try:
                nm = (ch.Name or "").strip()
            except Exception:
                nm = ""
            if nm.upper() == want:
                target = ch
                return
            walk(ch, depth + 1)

    walk(w)
    if target is None:
        return False
    try:
        target.Click(simulateMove=False)
        time.sleep(0.8)
        return True
    except Exception:
        try:
            r = target.BoundingRectangle
            pyautogui.click(r.xcenter(), r.ycenter())
            time.sleep(0.8)
            return True
        except Exception:
            return False


def steam_goto(section: str = "library") -> str:
    """Open a Steam section and VERIFY it actually switched.

    Deep-links alone often no-op when Steam is already open. We click the
    STORE / LIBRARY / COMMUNITY tab and only claim success after the UI
    shows the matching view (e.g. 'Community Supernav').
    """
    key = (section or "library").strip().lower()
    matched = None
    for name in STEAM_SECTIONS:
        if name in key or key in name:
            matched = name
            break
    if not matched:
        open_app("steam")
        return "Opening Steam."

    label = "library" if matched == "games" else matched
    if not _focus_steam():
        raise RuntimeError("I couldn't find or open the Steam window")

    def _ok(msg: str) -> str:
        _schedule_learn_safe("steam")
        try:
            import app_context
            app_context.set_app("steam")
        except Exception:
            pass
        return msg

    if _steam_verified(matched):
        return _ok(f"Steam {label} is already open.")

    # 1) Click the on-screen tab (primary — reliable for top nav).
    tab = STEAM_TAB_LABELS.get(matched)
    if tab:
        if _click_steam_tab(tab) and _steam_verified(matched):
            return _ok(f"Opened Steam {label}.")
        # Click without verify still often works; re-check after a beat.
        time.sleep(0.6)
        if _steam_verified(matched):
            return _ok(f"Opened Steam {label}.")

    # 2) Deep-links as backup (downloads / settings / friends).
    for url in STEAM_SECTIONS.get(matched, []):
        try:
            os.startfile(url)
            time.sleep(1.2)
            _focus_steam()
            if _steam_verified(matched):
                return _ok(f"Opened Steam {label}.")
        except Exception:
            continue

    # 3) Second click attempt.
    if tab and _click_steam_tab(tab):
        time.sleep(0.8)
        if _steam_verified(matched):
            return _ok(f"Opened Steam {label}.")

    raise RuntimeError(
        f"I tried to open Steam {label}, but Steam stayed on the previous page"
    )


_STEAM_ACCOUNT_SKIP = {
    "steam", "cancel", "ok", "add account", "add an account", "manage",
    "who's playing?", "who is playing?", "who's playing", "who is playing",
    "sign in", "login", "log in", "password", "username", "email",
    "remember me", "help", "quit", "exit", "close", "minimize", "maximize",
}


def _steam_account_candidates() -> list:
    """Clickable account entries on the Steam 'Who's playing?' picker."""
    import uiautomation as auto

    w = _steam_window()
    if not w:
        return []
    out = []
    seen = set()

    def walk(ctrl, depth=0):
        if depth > 12 or len(out) >= 12:
            return
        try:
            kids = ctrl.GetChildren()
        except Exception:
            return
        for ch in kids:
            walk(ch, depth + 1)
            try:
                nm = (ch.Name or "").strip()
                ctype = ch.ControlTypeName or ""
            except Exception:
                continue
            if not nm or len(nm) < 2:
                continue
            low = nm.lower()
            if low in _STEAM_ACCOUNT_SKIP or any(s in low for s in (
                "supernav", "download", "friends", "store", "library", "community",
            )):
                continue
            # Account rows are usually buttons / list items / custom controls with a name.
            if ctype not in (
                "ButtonControl", "ListItemControl", "HyperlinkControl",
                "MenuItemControl", "CustomControl", "TextControl",
            ):
                continue
            # Prefer larger clickable boxes (avatars / account tiles).
            try:
                r = ch.BoundingRectangle
                if r.width() < 40 or r.height() < 20:
                    continue
                key = (low, int(r.left), int(r.top))
            except Exception:
                key = (low, 0, 0)
            if key in seen:
                continue
            seen.add(key)
            out.append(ch)

    walk(w)
    # Prefer larger tiles (account cards) first — sort by area descending, keep order of discovery as tiebreaker
    scored = []
    for i, ch in enumerate(out):
        try:
            r = ch.BoundingRectangle
            area = max(1, r.width() * r.height())
        except Exception:
            area = 1
        scored.append((-area, i, ch))
    scored.sort()
    return [ch for _, _, ch in scored]


def steam_select_account(index: int = 1, name: str = "") -> str:
    """Pick a saved Steam account on the login / 'Who's playing?' screen.

    index is 1-based (first account = 1). Optional name matches account label.
    """
    idx = max(1, int(index or 1))
    want_name = (name or "").strip().lower()

    if not _focus_steam():
        raise RuntimeError("I couldn't find the Steam window. Open Steam first.")

    time.sleep(0.4)
    candidates = _steam_account_candidates()

    # Name match preferred.
    target = None
    if want_name:
        for ch in candidates:
            try:
                nm = (ch.Name or "").lower()
            except Exception:
                continue
            if want_name in nm or nm in want_name:
                target = ch
                break

    if target is None:
        if not candidates:
            # Vision/agent last resort for Chromium Steam login UI.
            try:
                import vision_agent
                if vision_agent.is_enabled():
                    goal = (
                        f"On the Steam login or 'Who's playing' screen, click the "
                        f"{idx}{'st' if idx==1 else 'nd' if idx==2 else 'rd' if idx==3 else 'th'} "
                        f"saved account"
                        + (f" named {name}" if name else "")
                        + " to sign in. Do not open a browser or Windows search."
                    )
                    return vision_agent.computer_use(goal)
            except Exception:
                pass
            raise RuntimeError(
                "I don't see any Steam accounts on screen. Make sure the "
                "'Who's playing?' login picker is open."
            )
        if idx > len(candidates):
            raise RuntimeError(
                f"Steam only showed {len(candidates)} account(s); there is no #{idx}."
            )
        target = candidates[idx - 1]

    label = ""
    try:
        label = (target.Name or "").strip()
    except Exception:
        label = f"account {idx}"

    try:
        target.Click(simulateMove=False)
    except Exception:
        r = target.BoundingRectangle
        pyautogui.click(r.xcenter(), r.ycenter())
    time.sleep(1.0)
    _schedule_learn_safe("steam")
    return f"Signing into Steam as {label or f'account {idx}'}."


def _resolve_site_url(site: str) -> str:
    """Turn 'youtube' / 'google maps' / 'foo.com' into a full https URL."""
    key = site.strip().lower()
    if key in WEB_SERVICES:
        return "https://" + WEB_SERVICES[key]
    compact = key.replace(" ", "")
    if compact.startswith("http://") or compact.startswith("https://"):
        return compact
    if "." not in compact:
        compact += ".com"
    return "https://" + compact


def _launch_url(url: str, browser: str = "") -> bool:
    """Open a URL in a specific browser if given, else the default browser."""
    browser = (browser or "").strip().lower()
    if browser and browser not in ("browser", "default", "the browser"):
        exe = _resolve_exe(BROWSER_EXES.get(browser, browser))
        if exe:
            subprocess.Popen([exe, url])
            return True
    webbrowser.open(url)
    return True


def search_web(query: str) -> str:
    import urllib.parse
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
    return f"Searching for {query}."


def open_website(site: str, browser: str = "") -> str:
    url = _resolve_site_url(site)
    _launch_url(url, browser)
    # Learn the browser chrome / site shell once it settles.
    _schedule_learn_safe((browser or "chrome").strip() or "chrome")
    where = f" in {browser}" if browser else ""
    return f"Opening {site}{where}."


def search_site(site: str, query: str, browser: str = "") -> str:
    """Search within a specific site, e.g. YouTube, Google Maps, Amazon."""
    import urllib.parse
    key = site.strip().lower()
    template = SITE_SEARCH.get(key)
    if template is None:
        # Not a known searchable site — open the site, or Google the query.
        if key in WEB_SERVICES:
            _launch_url(_resolve_site_url(key), browser)
            _schedule_learn_safe((browser or "chrome").strip() or "chrome")
            return f"Opening {site}."
        return search_web(query)
    url = template.format(q=urllib.parse.quote(query))
    _launch_url(url, browser)
    _schedule_learn_safe((browser or "chrome").strip() or "chrome")
    nice = "YouTube" if key in ("youtube", "yt") else site
    return f"Searching {nice} for {query}."


def type_text(text: str) -> str:
    pyautogui.write(text, interval=0.02)
    return f"Typed: {text}"


def press_keys(spoken: str) -> str:
    """Press a single key or a combo like 'control c' / 'alt tab'."""
    words = spoken.lower().replace(" plus ", " ").split()
    keys = [KEY_ALIASES.get(w, w) for w in words if w]
    if not keys:
        return "Which key?"
    try:
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        return f"Pressed {' + '.join(keys)}."
    except Exception:
        return f"I can't press {spoken}."


def click(button: str = "left", double: bool = False) -> str:
    if double:
        pyautogui.doubleClick()
        return "Double clicked."
    pyautogui.click(button=button)
    return f"{button.capitalize()} clicked."


def move_mouse(direction: str, amount: int = 200) -> str:
    dx, dy = 0, 0
    if direction == "up":
        dy = -amount
    elif direction == "down":
        dy = amount
    elif direction == "left":
        dx = -amount
    elif direction == "right":
        dx = amount
    pyautogui.moveRel(dx, dy, duration=0.2)
    return f"Moved mouse {direction}."


def mouse_to_center() -> str:
    pyautogui.moveTo(SCREEN_W // 2, SCREEN_H // 2, duration=0.2)
    return "Mouse centered."


def scroll(direction: str, clicks: int = 900, *, app: str = "") -> str:
    """Scroll the TARGET app's content — never the NEURON overlay by accident.

    Moves the mouse into the app window's content area, focuses it, then wheels.
    """
    target = (app or "").strip().lower()
    focused = False
    if target in ("steam",) or "steam" in target:
        focused = _focus_steam()
        if focused:
            try:
                import app_context
                app_context.set_app("steam")
            except Exception:
                pass
    elif target:
        focused = _focus_window_by_title(target)

    # Put cursor over the main content (center of foreground / steam window)
    # so the wheel hits the community feed / library list, not the title bar.
    try:
        import uiautomation as auto
        root = auto.GetForegroundControl()
        if root:
            rect = root.BoundingRectangle
            # Aim slightly below center — below Steam's tab strip / URL bar.
            cx = rect.xcenter()
            cy = int(rect.top + rect.height() * 0.62)
            if rect.width() > 100 and rect.height() > 100:
                pyautogui.moveTo(cx, cy, duration=0.12)
                pyautogui.click()
                time.sleep(0.12)
    except Exception:
        pyautogui.moveTo(SCREEN_W // 2, int(SCREEN_H * 0.55), duration=0.1)
        pyautogui.click()
        time.sleep(0.1)

    amount = abs(int(clicks))
    # Several wheel ticks — Steam webviews often need more than one notch.
    steps = 6
    per = max(120, amount // steps)
    for _ in range(steps):
        pyautogui.scroll(per if direction == "up" else -per)
        time.sleep(0.04)
    where = target or "window"
    return f"Scrolled {direction} in {where}."


def _focus_window_by_title(name: str) -> bool:
    """Focus a top-level window whose title contains name."""
    key = (name or "").strip().lower()
    if not key:
        return False
    try:
        import uiautomation as auto
        for ch in auto.GetRootControl().GetChildren():
            try:
                if ch.ControlTypeName != "WindowControl":
                    continue
                title = (ch.Name or "").strip().lower()
                if key in title and "n.e.u.r.o.n" not in title:
                    ch.SetActive()
                    time.sleep(0.3)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def volume(action: str) -> str:
    key = {"up": "volumeup", "down": "volumedown", "mute": "volumemute"}[action]
    for _ in range(5 if action != "mute" else 1):
        pyautogui.press(key)
    return f"Volume {action}."


def media(action: str) -> str:
    key = {
        "playpause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
    }[action]
    pyautogui.press(key)
    return "Done."


def window(action: str) -> str:
    if action == "close":
        pyautogui.hotkey("alt", "f4")
        return "Window closed."
    if action == "minimize":
        pyautogui.hotkey("win", "down")
        return "Minimized."
    if action == "maximize":
        pyautogui.hotkey("win", "up")
        return "Maximized."
    if action == "switch":
        pyautogui.hotkey("alt", "tab")
        return "Switched window."
    if action == "desktop":
        pyautogui.hotkey("win", "d")
        return "Showing desktop."
    return "Unknown window action."


# Process image names for "close X" when it's a desktop app (not a website).
_CLOSE_PROCESSES = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "firefox": "firefox.exe",
    "brave": "brave.exe",
    "notepad": "notepad.exe",
    "spotify": "spotify.exe",
    "discord": "discord.exe",
    "steam": "steam.exe",
    "code": "code.exe",
    "vscode": "code.exe",
    "vs code": "code.exe",
    "cursor": "cursor.exe",
    "calculator": "calculator.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
}


def close_app(name: str) -> str:
    """Close a named app/window. 'close chrome' closes the browser — never clicks page text."""
    import subprocess
    import time as _time

    key = (name or "").strip().lower()
    key = re.sub(r"\b(the|app|application|program|window|please)\b", " ", key)
    key = re.sub(r"\s+", " ", key).strip(" .!?")
    if not key:
        return window("close")

    # Controlled Playwright Chrome — this is what "close chrome" almost always means
    # when NEURON has a browser open with the automation banner.
    if key in ("chrome", "google chrome", "browser", "the browser"):
        try:
            import browser as br
            if br.supported():
                return br.close_browser()
        except Exception:
            pass

    # Focus a matching top-level window, then Alt+F4.
    focused = False
    try:
        import uiautomation as auto
        root = auto.GetRootControl()
        needle = key
        for win in root.GetChildren():
            try:
                title = (win.Name or "").lower()
                if not title or needle not in title:
                    # Also match known app titles loosely
                    if needle == "notepad" and "notepad" not in title:
                        continue
                    if needle not in title:
                        continue
                win.SetFocus()
                focused = True
                _time.sleep(0.25)
                break
            except Exception:
                continue
    except Exception:
        pass

    if focused:
        pyautogui.hotkey("alt", "f4")
        return f"Closed {key}."

    # Last resort: end the process (single-app tools like notepad).
    exe = _CLOSE_PROCESSES.get(key)
    if exe and exe not in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                capture_output=True, text=True, timeout=8,
            )
            return f"Closed {key}."
        except Exception as exc:
            return f"Couldn't close {key}: {exc}"

    # Browser fallback without playwright handle — Alt+F4 on whatever is focused is wrong;
    # try taskkill only if user explicitly said chrome and we couldn't use browser module.
    if exe in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                capture_output=True, text=True, timeout=8,
            )
            return f"Closed {key}."
        except Exception as exc:
            return f"Couldn't close {key}: {exc}"

    return f"I couldn't find {key} to close."


def screenshot(all_monitors: bool = True) -> str:
    folder = os.path.join(os.path.expanduser("~"), "Pictures", "NEURON")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        import screen_capture as sc
        if all_monitors:
            shots = sc.capture_all_monitors()
            paths = []
            for shot in shots:
                mon = shot["monitor"]
                path = os.path.join(folder, f"shot_{stamp}_M{mon.id}.png")
                shot["image"].save(path)
                paths.append(path)
            # Also save a full virtual-desktop stitch
            full_path = os.path.join(folder, f"shot_{stamp}_all.png")
            sc.capture_virtual_desktop().save(full_path)
            return (
                f"Saved {len(paths)} monitor shot(s) plus a full desktop stitch "
                f"to Pictures\\NEURON."
            )
    except Exception:
        pass
    path = os.path.join(folder, f"shot_{stamp}.png")
    pyautogui.screenshot(path)
    return f"Screenshot saved to Pictures, NEURON folder."


def _special_folder(name: str) -> str:
    """Resolve Desktop/Downloads/etc. correctly, even when OneDrive-redirected."""
    reg_names = {
        "desktop": "Desktop",
        "documents": "Personal",
        "docs": "Personal",
        "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
        "pictures": "My Pictures",
        "music": "My Music",
        "videos": "My Video",
    }
    key = reg_names.get(name.strip().lower())
    if key:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as k:
                return os.path.expandvars(winreg.QueryValueEx(k, key)[0])
        except OSError:
            pass
    # Fallback: treat the name as an absolute path or home-relative
    if os.path.isabs(name):
        return name
    return os.path.join(os.path.expanduser("~"), name)


def create_folder(name: str, location: str = "desktop") -> str:
    base = _special_folder(location) if not os.path.isabs(name) else ""
    path = name if os.path.isabs(name) else os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return f"Created folder {name}."


def create_file(name: str, content: str = "", location: str = "desktop") -> str:
    base = _special_folder(location) if not os.path.isabs(name) else ""
    path = name if os.path.isabs(name) else os.path.join(base, name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Created file {os.path.basename(path)}."


def open_folder(location: str) -> str:
    loc = (location or "").strip().lower()
    path = _special_folder(loc)
    if os.path.isdir(path):
        os.startfile(path)
        return f"Opening {loc}."
    # Resolve from PC inventory (child folders under Desktop/Documents/...)
    try:
        import pc_trainer
        data = pc_trainer.load_inventory() or {}
        needle = loc
        for folder in data.get("folders") or []:
            fname = (folder.get("name") or "").lower()
            fpath = folder.get("path") or ""
            if fname == needle and fpath and os.path.isdir(fpath):
                os.startfile(fpath)
                return f"Opening {folder.get('name')}."
            for child in folder.get("children") or []:
                cname = (child.get("name") or "").lower()
                cpath = child.get("path") or ""
                if (cname == needle or needle in cname) and cpath and os.path.isdir(cpath):
                    os.startfile(cpath)
                    return f"Opening {child.get('name')}."
    except Exception:
        pass
    return f"I couldn't find the {location} folder."


def run_shell(command: str) -> str:
    """Run a PowerShell command and verify it succeeded (used by the LLM brain).

    Raises RuntimeError with the real error text if the command fails, so the
    brain reports honestly instead of claiming false success. A command that
    keeps running (e.g. launches an app) is treated as started, not failed.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return "Started."
    if result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        raise RuntimeError(err[0] if err else f"exit code {result.returncode}")
    return "Done."


def wait(seconds: float) -> str:
    time.sleep(min(float(seconds), 5))
    return ""


def lock_pc() -> str:
    subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
    return "Locking your computer."


def battery_status() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "I can't read a battery on this machine."
        state = "charging" if b.power_plugged else "on battery"
        return f"Battery is at {int(b.percent)} percent, {state}."
    except Exception:
        return "I couldn't read the battery."


def cpu_status() -> str:
    try:
        import psutil
        pct = psutil.cpu_percent(interval=0.5)
        return f"CPU is at {int(pct)} percent."
    except Exception:
        return "I couldn't read the CPU."


def ram_status() -> str:
    try:
        import psutil
        m = psutil.virtual_memory()
        used = round((m.total - m.available) / 1e9, 1)
        total = round(m.total / 1e9, 1)
        return f"Memory: {used} of {total} gigabytes used, {int(m.percent)} percent."
    except Exception:
        return "I couldn't read memory."


def system_report() -> str:
    return " ".join([battery_status(), cpu_status(), ram_status()])


def current_time() -> str:
    return "It's " + datetime.now().strftime("%I:%M %p").lstrip("0") + "."


def current_date() -> str:
    return "Today is " + datetime.now().strftime("%A, %B %d, %Y") + "."
