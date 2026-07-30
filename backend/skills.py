"""Local skill recipes for N.E.U.R.O.N's agent loop.

Compact, high-signal examples the planner must follow. Keep short —
every token slows voice latency.
"""

SKILLS = """
SKILL RECIPES (match normal speech → these actions):
- "learn my computer" / "map my pc" → train_pc {deep_learn:true}  (inventory ALL apps; optional deep learn)
- "quick scan my computer" → train_pc {deep_learn:false}  (inventory only, no UI spam)
- "learn how steam/youtube works" → learn_app {name}  (ONE app deep UI — only when asked)
- "what do you know about steam" → recall learned knowledge
- "training status" → training_status {}
- Unknown app UI / "click that button" → computer_use {goal}  (works without deep-learning every app)
- "open chrome/notepad/spotify" → open_app {name}  (SHORT app name ONLY)
- "close chrome/notepad/spotify" → close_app {name}  NEVER click_text "Close"
- "stop talking / be quiet / shut up" → stop speech (no other action)
- "look at monitor 1/2" → focus that monitor, then follow-up actions use it
- "open youtube/gmail/maps" → open_website {site}  (websites ≠ open_app)
- "scroll down/up (on youtube/page)" → page_scroll {direction}  OR scroll {direction}
- "come back / go back / go to youtube home (page/screen)" → youtube_home {}  (NEVER play a video)
- "play Nth video on youtube home" → youtube_home_play {index:N}  (ONE step; Nth **on screen**)
- "how many / what videos on screen" → list_visible_videos {}  (titles from the page, NOT play)
- "play the 2nd video on screen" / after scrolling → play_result {index:N}  (what you see NOW)
- "play <name>" / "play the video called X" (YouTube already open) → play_by_title {title}
- "search X on youtube" → search_site {site:youtube, query:X} then play_result {index:1}
- "skip ad" → skip_ad {}
- "fullscreen" / "exit fullscreen" → fullscreen {} / fullscreen {exit:true}
- "minimize the video" / "miniplayer" → miniplayer {}  NEVER window minimize
- "minimize the window" → window {action:minimize}
- "pause/play the video" → ensure_playback {want:pause|play}
- "mute youtube/video" → player_key {key:m}   (not volume mute)
- "next/previous video" → player_key {key:Shift+N|Shift+P}
- "open steam library/store" → steam_goto {section}
- "open steam friends" → steam_goto {section:friends}
- "open friends chat" / "open discord friends" / "open dms" → discord_friends {}
- "open windows settings" / "bluetooth settings" → open_settings {page}
- "remember that as X" / "when I say X" → teach voice recipe (after a successful action)
- "train priority apps" → install Discord/YouTube/Google/Opera/Settings/Steam/Blender/Notepad/WhatsApp playbooks
- "learn from youtube how to X" / "ask google how to X" → research tutorials → save voice recipes + click targets
- "start recording clicks" → record mouse workflow; "stop recording" / "remember that as X" → save
- "replay X" / "list click recipes" → replay_clicks / list saved click workflows
- "login to the first steam account" → steam_select_account {index:1}
- "close the window" → window {action:close} ; "close the tab" → press_keys {keys:control w}
- "volume up/down/mute" → volume {action}
- "what's on my screen" / "how many X on screen" → answer_screen / describe_screen
  (foreground app screenshot + UI Automation + VLM — works for ANY app)
- "how many / what videos on screen" (YouTube open) → list_visible_videos {}
- "click that" / visual deixis → computer_use {goal}
- "learn how youtube/steam works" → learn_app {name}
- "learn my computer" → train_pc {deep_learn:true}
HARD BANS:
- NEVER open_app with a sentence ("the first account in steam") — that opens Windows Search/Bing.
- NEVER search_web for desktop actions (login, click, open account, close app).
- Prefer plain verbs: open, close, pause, play, scroll, mute — not slang.
LANGUAGE:
- User speaks normally ("open chrome", "close chrome"). Understand that.
- Ignore filler only: please, can you, hey neuron, for me.
- Hands-free: user does NOT need to say Neuron — plain commands are enough.
- "minimize the video" ≠ "minimize the window".
AGENT LOOP:
1) Pick the smallest correct action list (usually 1 step).
2) Prefer specific tools over computer_use / run_shell / search.
3) Prefer PC INVENTORY / LEARNED APP MEMORY over guessing.
4) Never invent Done with empty steps when an action exists.
5) Never claim success in say without the step that does it.
"""


def for_prompt() -> str:
    return SKILLS.strip()
