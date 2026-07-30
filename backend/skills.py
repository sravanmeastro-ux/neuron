"""Local skill recipes for N.E.U.R.O.N's agent loop.

Compact, high-signal examples the planner must follow. Keep short —
every token slows voice latency.

Callable domain skills also live under neuron.skills:
  youtube.search / windows.move_to_monitor / spotify.play / …
"""

SKILLS = """
SKILL RECIPES (match normal speech → these actions):
- Prefer DOMAIN SKILLS when they fit: youtube.* browser.* windows.* spotify.* discord.* files.* blender.*
- "learn how I create a Blender project" → teach procedure (demonstrate + save skill). NEVER edit NEURON source.
- "create a Blender project" → run learned/builtin procedure blender.new_project
- "list procedures" / "forget skill X" → manage learned workflows
- "learn my computer" / "map my pc" → train_pc {deep_learn:true}  (inventory ALL apps; optional deep learn)
- "quick scan my computer" → train_pc {deep_learn:false}  (inventory only, no UI spam)
- "learn how steam/youtube works" → learn_app {name}  (ONE app deep UI — only when asked)
- "what do you know about steam" → recall learned knowledge
- "training status" → training_status {}
- Unknown app UI / "click that button" → computer_use {goal}  (works without deep-learning every app)
- "open chrome/notepad/spotify" → windows.open_app {name}  OR open_app {name}  (SHORT app name ONLY)
- "close chrome/notepad/spotify" → windows.close_app {name}  NEVER click_text "Close"
- "stop talking / be quiet / shut up" → stop speech (no other action)
- "look at monitor 1/2" → focus that monitor, then follow-up actions use it
- "move chrome to monitor 2" → windows.move_to_monitor {name:chrome, monitor:2}
- "open youtube/gmail/maps" → browser.open_tab {url}  OR open_website {site}
- "scroll down/up (on youtube/page)" → page_scroll {direction}  OR scroll {direction}
- "come back / go back / go to youtube home" → youtube.home {}  (NEVER play a video)
- "play Nth video on youtube home" → youtube_home_play {index:N}  OR youtube.play_result after home
- "how many / what videos on screen" → youtube.list_videos {}
- "play the 2nd video on screen" → youtube.play_result {index:N}
- "play <name>" (YouTube already open) → youtube.play_by_title {title}
- "search X on youtube" → youtube.search {query:X} then youtube.play_result {index:1}
  OR youtube.play_search {query:X}
- "newest channel video" → youtube.open_channel_videos {channel} then youtube.play_result {index:1}
- "skip ad" → youtube.skip_ad {}
- "fullscreen" / "exit fullscreen" → youtube.fullscreen {} / youtube.fullscreen {exit:true}
- "minimize the video" / "miniplayer" → miniplayer {}  NEVER window minimize
- "minimize the window" → windows.minimize {name} OR window {action:minimize}
- "pause/play the video" → youtube.ensure_playback {want:pause|play}
- "mute youtube/video" → player_key {key:m}   (not volume mute)
- "next/previous video" → player_key {key:Shift+N|Shift+P}
- "play spotify" / "play X on spotify" → spotify.play {query?}
- "open discord friends/dms" → discord.friends {} OR discord.open_channel {channel:friends}
- "open steam library/store" → steam_goto {section}
- "open windows settings" / "bluetooth settings" → open_settings {page}
- "find my report.pdf" → files.find {query} ; open it → files.open {path|query}
- "open blender project X" → blender.open_project {path|query}
- "remember that as X" / "when I say X" → teach voice recipe (after a successful action)
- "train priority apps" → install Discord/YouTube/Google/Opera/Settings/Steam/Blender/Notepad/WhatsApp playbooks
- "learn from youtube how to X" / "ask google how to X" → research tutorials → save voice recipes + click targets
- "start recording clicks" → record mouse workflow; "stop recording" / "remember that as X" → save
- "replay X" / "list click recipes" → replay_clicks / list saved click workflows
- "login to the first steam account" → steam_select_account {index:1}
- "close the window" → window {action:close} ; "close the tab" → browser.close_tab {}
- "volume up/down/mute" → volume {action}
- "what's on my screen" / "how many X on screen" → answer_screen / describe_screen
- "click that" / visual deixis → computer_use {goal} OR click_element {name}
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
1) Pick the smallest correct action list (usually 1 step). Prefer a domain skill when it matches.
2) Prefer specific tools / skills over computer_use / run_shell / search.
3) Prefer PC INVENTORY / LEARNED APP MEMORY over guessing.
4) Never invent Done with empty steps when an action exists.
5) Never claim success in say without the step that does it.
"""


def for_prompt() -> str:
    chunks = [SKILLS.strip()]
    try:
        from neuron.skills.registry import skill_prompt
        chunks.append(skill_prompt())
    except Exception:
        pass
    try:
        from neuron.safety.levels import tier_prompt
        chunks.append(tier_prompt())
    except Exception:
        pass
    return "\n\n".join(chunks)
