"""How common apps work — injected into the reasoning brain so NEURON
plans real workflows instead of guessing.

Keep entries short, action-oriented, and tied to the available tools.
"""

YOUTUBE = """
YOUTUBE (website — never open_app):
- Homepage feed: youtube_home_play {index:N} plays the Nth video **visible on screen**
  (viewport tiles, top→bottom left→right) — not the Nth item in the full page DOM,
  and not a half-scrolled-off row at the top.
- "come back to youtube home" / "go to youtube homepage" -> youtube_home {} ONLY.
  Never youtube_home_play / play_result when the user only wants the home screen.
- "play the 2nd video on screen" / "play the 2nd video" after scrolling -> play_result {index:2}
  uses tiles visible in the browser window RIGHT NOW (not the top of the homepage).
- "play the 2nd video on the youtube homepage" -> youtube_home_play {index:2} only.
- Play by name when YouTube is open: play_by_title {title:"..."} matches visible feed titles.
  Prefer this over ordinals: "play iron man suit up" / "play the video called X".
- Search then play: search_site {site:youtube, query:...} THEN play_result {index:N}
- "skip the ad" / "skip add" / "skip sad" (speech mishear) -> skip_ad ONLY.
  Never reopen homepage or re-play a video when the user asks to skip an ad.
- "fullscreen the video" / "make it fullscreen" / "go fullscreen" -> fullscreen {}
  (YouTube player shortcut 'f'). NEVER window maximize. Maximize is for windows only.
- "exit fullscreen" -> fullscreen {exit:true}
- "pause/play the video" -> ensure_playback pause|play (absolute, never toggle).
- "mute youtube" -> player_key m.
- "next video" -> player_key Shift+N. "previous video" -> Shift+P.
  ("next song" is media next — different.)
- Prefer skip_ad / play_by_title / play_result / youtube_home_play / fullscreen / ensure_playback over computer_use.
- Do NOT use media playpause for picking a specific video.
- Each spoken request is independent — do not repeat the last YouTube play unless asked again.
"""

STEAM = """
STEAM (desktop app — NEVER a website, NEVER open_website / play_result / search_web):
- "open steam" -> open_app {name:steam}  (short name only)
- "open library/community/store in steam" -> steam_goto {section:...}
  steam_goto CLICKS the top tab and VERIFIES the view changed. Do not invent success.
- "open/login first account in steam" / "Who's playing" -> steam_select_account {index:1}
- "login as Bob on steam" -> steam_select_account {name:Bob}
  NEVER open_app("the first account in steam") — that types into Windows Search / Bing.
- Other sections: friends, downloads, settings, news -> steam_goto
- Never use the controlled Chrome browser for Steam UI.
"""

CHROME = """
CHROME / EDGE (desktop browsers):
- Opening a SITE: open_website, not open_app chrome + typing.
- open_app chrome only when the user explicitly wants the browser app itself.
- Page actions (click Nth result, click by text) only work in NEURON's
  controlled browser (open_website / search_site open that one).
"""

NOTEPAD = """
NOTEPAD:
- open_app notepad, wait 1, type_text, optionally press_keys control s to save.
"""

FILE_EXPLORER = """
FILES / FOLDERS:
- Prefer create_folder / create_file / open_folder over run_shell.
- Locations: desktop, documents, downloads, pictures, music, videos.
"""

GENERAL = """
GENERAL APP RULES:
- Web services (youtube, gmail, maps, netflix, amazon...) = open_website / search_site.
- Desktop programs (notepad, steam, spotify app, vscode) = open_app / steam_goto.
- open_app takes a SHORT app name only ("steam", "notepad"). Never a full sentence.
- Windows Start Search / Bing is FORBIDDEN for task phrases — use tools or computer_use.
- If a task needs seeing inside a non-web app, use computer_use as last resort.
- If LEARNED APP MEMORY is present for an app, FOLLOW it (voice_commands / deep_links).
- "learn/read/study this app" -> learn_app. Do not invent knowledge — scan and save.
- HONESTY: never say an action succeeded unless the tool result confirms it.
  Prefer tools that verify (steam_goto, steam_select_account, play_result, ensure_playback).
- Apps are auto-learned when opened/focused (app memory). Prefer LEARNED APP MEMORY.
- Always chain the steps that finish the job. Opening a page is not the same
  as playing / clicking / typing. Verify the final action is in the plan.
- Never reply as if the task succeeded when steps are empty.
- Questions about LIVE facts (weather, news, prices, sports scores, stocks)
  are NOT conversation: use search_web with a clear query.
- Pure opinions/greetings/small talk: empty steps, answer in say.
- Desktop control ("login", "click account", "open the first…") is NEVER search_web.
"""


def for_prompt() -> str:
    return "\n".join([
        "APP KNOWLEDGE (how to use apps correctly):",
        YOUTUBE.strip(),
        STEAM.strip(),
        CHROME.strip(),
        NOTEPAD.strip(),
        FILE_EXPLORER.strip(),
        GENERAL.strip(),
    ])
