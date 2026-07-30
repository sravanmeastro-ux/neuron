"""NEURON rules test suite — verifies spoken sentences route to the RIGHT action.

Run:  python tests/run_rules_tests.py   (from the backend folder)

Includes conflict/regression cases so mistakes like fullscreen→maximize
cannot silently come back.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import brain  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls = []

    def make(self, name, ret=None):
        def f(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return ret if ret is not None else f"{name} ok"
        return f

    def called(self, name):
        return any(c[0] == name for c in self.calls)

    def first(self, name):
        for c in self.calls:
            if c[0] == name:
                return c
        return None

    def reset(self):
        self.calls.clear()


rec = Recorder()


class FakeBrowser:
    def open_site(self, url):
        rec.calls.append(("open_site", (url,), {}))
        return f"Opened {url}."

    def youtube_search(self, q):
        rec.calls.append(("youtube_search", (q,), {}))
        return f"Searching YouTube for {q}."

    def search(self, url, label):
        rec.calls.append(("web_search", (url, label), {}))
        return label

    def play_result(self, n):
        rec.calls.append(("play_result", (n,), {}))
        return f"Playing video {n}."

    def youtube_home_play(self, n):
        rec.calls.append(("youtube_home_play", (n,), {}))
        return f"Playing home video {n}."

    def youtube_home(self):
        rec.calls.append(("youtube_home", (), {}))
        return "Back on the YouTube homepage."

    def skip_ad(self):
        rec.calls.append(("skip_ad", (), {}))
        return "Skipped the ad."

    def fullscreen(self, exit_fs=False):
        rec.calls.append(("fullscreen", (exit_fs,), {}))
        return "Exited fullscreen." if exit_fs else "YouTube is fullscreen."

    def miniplayer(self):
        rec.calls.append(("miniplayer", (), {}))
        return "Video is in miniplayer."

    def player_key(self, key):
        rec.calls.append(("player_key", (key,), {}))
        return f"key {key}"

    def ensure_playback(self, want="play"):
        rec.calls.append(("ensure_playback", (want,), {}))
        return f"ensure {want}"

    def click_text(self, t):
        rec.calls.append(("click_text", (t,), {}))
        return f"Clicked {t}."

    def page_scroll(self, direction="down", amount=900):
        rec.calls.append(("page_scroll", (direction, amount), {}))
        return f"Scrolled {direction}."

    def play_by_title(self, title):
        rec.calls.append(("play_by_title", (title,), {}))
        return f"Playing by title: {title}."

    def list_visible_videos(self):
        rec.calls.append(("list_visible_videos", (), {}))
        return "I can see 5 videos on screen: 1) Demo A; 2) Demo B."

    def close_browser(self):
        rec.calls.append(("close_browser", (), {}))
        return "Closed Chrome."

    def current_url(self):
        rec.calls.append(("current_url", (), {}))
        return "https://www.youtube.com/watch?v=test"

    def learn_snapshot(self, site_hint=""):
        rec.calls.append(("learn_snapshot", (site_hint,), {}))
        return {
            "url": "https://www.youtube.com/",
            "title": "YouTube",
            "labels": ["Home", "Shorts", "Subscriptions", "Search"],
            "isYouTube": True,
            "path": "/",
        }

    def on_youtube(self):
        return getattr(self, "_on_youtube", False)


def install_mocks():
    brain.browser = FakeBrowser()
    brain._BROWSER = True

    a = brain.actions
    for name in [
        "open_app", "type_text", "press_keys", "click", "move_mouse",
        "mouse_to_center", "scroll", "volume", "media", "window",
        "screenshot", "lock_pc", "battery_status", "cpu_status",
        "ram_status", "system_report", "current_time", "current_date",
        "search_web", "open_website", "search_site", "steam_goto",
        "steam_select_account", "discord_friends", "open_settings",
        "open_folder", "close_app",
    ]:
        setattr(a, name, rec.make(name))

    brain.memory.remember = rec.make("mem_remember")
    brain.memory.recall = lambda k: rec.calls.append(("mem_recall", (k,), {})) or "red"
    brain.memory.log = lambda *a, **k: None
    brain.memory.context_blob = lambda request="": ""

    brain.app_learner.learn_app = lambda name="", **kw: (
        rec.calls.append(("learn_app", (name,), {})) or "Done. Learned."
    )
    brain.app_learner.learn_website = lambda site="youtube", **kw: (
        rec.calls.append(("learn_website", (site,), {})) or "Done. Learned website."
    )
    brain.app_learner.recall_summary = lambda name: (
        rec.calls.append(("recall_summary", (name,), {})) or f"I know {name}."
    )

    import re as _re
    import howto_learn
    howto_learn.learn_from_utterance = lambda text: (
        rec.calls.append(("howto_learn", (text,), {})) or "Learned from the web."
        if _re.search(r"youtube|google|tutorial|internet|ask google|learn from|train from", text, _re.I)
        else None
    )

    class FakeVision:
        @staticmethod
        def is_enabled():
            return True

        @staticmethod
        def needs_glance(text):
            return False

        @staticmethod
        def quick_screen_context(request="", force_vlm=False):
            return ""

        @staticmethod
        def describe_screens(request="", monitor_id=None):
            rec.calls.append(("describe_screen", (request, monitor_id), {}))
            return "I see your screens."

        @staticmethod
        def answer_screen(request="", monitor_id=None):
            rec.calls.append(("answer_screen", (request, monitor_id), {}))
            return "I see the front app."

        @staticmethod
        def computer_use(goal, max_steps=None):
            rec.calls.append(("computer_use", (goal,), {}))
            return "done"
    brain.vision_agent = FakeVision()

    brain.brain_llm.is_enabled = lambda: True
    brain.brain_llm.plan = (
        lambda raw, ctx="", model=None, normalized="":
        rec.calls.append(("llm_plan", (raw,), {})) or {"say": "", "steps": []}
    )
    brain.brain_llm.chat_json = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("rules suite: chat_json mocked offline")
    )
    # This suite asserts regex/recipe routes — not the Phase 1 Ollama planner.
    brain._agent_config = lambda: {
        "enabled": True,
        "agent_first": False,
        "legacy_fallback": True,
        "max_replans": 0,
        "tool_timeout_seconds": 5,
    }

    import click_recorder
    click_recorder.start = rec.make("click_start", "Recording your clicks.")
    click_recorder.stop = rec.make("click_stop", "Saved clicks.")
    click_recorder.cancel = rec.make("click_cancel", "Cancelled.")
    click_recorder.list_recipes = rec.make("click_list", "No recipes.")
    click_recorder.status = rec.make("click_status", "Not recording.")
    click_recorder.replay = rec.make("click_replay", "Replayed.")
    click_recorder.is_recording = lambda: False


# (sentence, expected_call, arg_check or None)
CASES = [
    # --- YouTube / browser -------------------------------------------------
    ("play the second video in the youtube homepage", "youtube_home_play", lambda c: c[1] == (2,)),
    ("I want you to play the 2nd video on the YouTube home page.", "youtube_home_play", lambda c: c[1] == (2,)),
    # "on youtube" / "on screen" = current scrolled view, not absolute homepage index
    ("play the third video on youtube", "play_result", lambda c: c[1] == (3,)),
    ("play the 3rd result", "play_result", lambda c: c[1] == (3,)),
    ("play the second video on screen", "play_result", lambda c: c[1] == (2,)),
    ("playing the second video on screen", "play_result", lambda c: c[1] == (2,)),
    ("play the 2nd video i can see", "play_result", lambda c: c[1] == (2,)),
    ("skip the ad", "skip_ad", None),
    ("skip the add in the youtube", "skip_ad", None),
    ("skip the sad", "skip_ad", None),
    ("can you skip this ad", "skip_ad", None),
    ("search for iron man suit on youtube", "youtube_search", lambda c: "iron man suit" in c[1][0]),
    ("youtube search jarvis best scenes", "youtube_search", None),
    # Not on YouTube yet → search. On YouTube → play_by_title (see CASES_ON_YT).
    ("play despacito on youtube", "youtube_search", None),
    ("open youtube", "open_site", lambda c: "youtube" in c[1][0]),
    ("come back to youtube home screen", "youtube_home", None),
    ("go back to youtube homepage", "youtube_home", None),
    ("go to youtube home", "youtube_home", None),
    ("open youtube homepage", "youtube_home", None),
    ("open you tube", "open_site", lambda c: "youtube" in c[1][0]),
    ("go to github.com", "open_site", lambda c: "github" in c[1][0]),
    ("click on the sign in button", "click_text", lambda c: "sign in" in c[1][0]),
    ("search for weather in delhi today", "web_search", None),
    # --- desktop apps --------------------------------------------------------
    ("open chrome", "open_app", lambda c: c[1][0] == "chrome"),
    ("open crome", "open_app", lambda c: c[1][0] == "chrome"),
    ("open notepad", "open_app", None),
    ("open note pad", "open_app", lambda c: c[1][0] == "notepad"),
    ("open steam", "open_app", None),
    ("in steam open library", "steam_goto", None),
    ("open the library tab in steam", "steam_goto", None),
    ("steam store", "steam_goto", None),
    ("open friends chat", "discord_friends", None),
    ("open friend chat", "discord_friends", None),
    ("open discord friends", "discord_friends", None),
    ("open dms", "discord_friends", None),
    ("open steam friends", "steam_goto", None),
    ("steam friends chat", "steam_goto", None),
    ("start recording clicks", "click_start", None),
    ("stop recording", "click_stop", None),
    ("list click recipes", "click_list", None),
    ("replay my workflow", "click_replay", None),
    ("learn from youtube how to open discord friends", "howto_learn", None),
    ("ask google how to render in blender", "howto_learn", None),
    ("open youtube", "open_site", None),
    ("open youtube in chrome", "open_site", None),
    ("learn how youtube works", "learn_website", lambda c: "youtube" in str(c[1])),
    ("read how youtube works", "learn_website", None),
    ("open the first account in steam", "steam_select_account", lambda c: c[1][0] == 1),
    ("login to the first steam account", "steam_select_account", lambda c: c[1][0] == 1),
    ("sign in to second account on steam", "steam_select_account", lambda c: c[1][0] == 2),
    ("login as bob on steam", "steam_select_account", None),
    ("learn how steam works", "learn_app", None),
    ("analyze how steam works", "learn_app", None),
    ("analyse how steam works", "learn_app", None),
    ("study how notepad works", "learn_app", None),
    ("read this app and learn how it works", "learn_app", None),
    ("study the app", "learn_app", None),
    # --- typing & keys -------------------------------------------------------
    ("type hello world", "type_text", lambda c: c[1][0] == "hello world"),
    ("press enter", "press_keys", None),
    ("press control s", "press_keys", None),
    ("write a poem in notepad", "llm_plan", None),
    # --- mouse ---------------------------------------------------------------
    ("double click", "click", lambda c: c[2].get("double") is True),
    ("right click", "click", lambda c: c[2].get("button") == "right"),
    ("scroll down", "scroll", None),
    ("scroll down on youtube", "page_scroll", lambda c: c[1][0] == "down"),
    ("scroll up youtube", "page_scroll", lambda c: c[1][0] == "up"),
    ("youtube scroll down", "page_scroll", None),
    ("scroll the feed down", "page_scroll", None),
    ("move the mouse up", "move_mouse", None),
    # --- volume & media ------------------------------------------------------
    ("volume up", "volume", lambda c: c[1] == ("up",)),
    ("make it louder", "volume", lambda c: c[1] == ("up",)),
    ("mute", "volume", lambda c: c[1] == ("mute",)),
    ("pause", "media", None),
    ("pause the music", "media", None),
    ("next song", "media", lambda c: c[1] == ("next",)),
    ("skip this track", "media", lambda c: c[1] == ("next",)),
    ("play despacito", "llm_plan", None),
    # --- windows -------------------------------------------------------------
    ("close the window", "window", lambda c: c[1] == ("close",)),
    ("close the tab", "press_keys", None),
    ("close chrome", "close_app", lambda c: "chrome" in str(c[1][0]).lower()),
    ("close google chrome", "close_app", None),
    ("quit notepad", "close_app", None),
    ("exit spotify", "close_app", None),
    ("minimize the window", "window", lambda c: c[1] == ("minimize",)),
    ("maximize the window", "window", lambda c: c[1] == ("maximize",)),
    ("show the desktop", "window", lambda c: c[1] == ("desktop",)),
    ("go to desktop", "window", lambda c: c[1] == ("desktop",)),
    ("switch window", "window", lambda c: c[1] == ("switch",)),
    # --- system --------------------------------------------------------------
    ("take a screenshot", "screenshot", None),
    ("take a screen shot", "screenshot", None),
    ("lock the computer", "lock_pc", None),
    ("lock screen", "lock_pc", None),
    ("battery", "battery_status", None),
    ("how much ram do i have", "ram_status", None),
    ("system report", "system_report", None),
    ("open downloads", "open_folder", None),
    ("open documents", "open_folder", None),
    # --- memory --------------------------------------------------------------
    ("remember that my favorite color is red", "mem_remember", None),
    ("what is my favorite color", "mem_recall", None),
    # --- small talk ----------------------------------------------------------
    ("what time is it", "current_time", None),
    ("what's the date today", "current_date", None),
    ("how are you doing", "llm_plan", None),  # may be small-talk; see runner soft-match
    # --- vision --------------------------------------------------------------
    ("take control and click the start button", "computer_use", None),
    ("what's on my screen", "answer_screen", None),
    ("what is on my screens", "answer_screen", None),
    ("describe my monitors", "answer_screen", None),
    ("look at monitor 1", "describe_screen", None),
    ("stop talking", "__STOP_SPEECH__", None),
    ("click that button on the other screen", "computer_use", None),
    ("click on that", "computer_use", None),
    # --- reasoning-brain fallbacks -------------------------------------------
    ("create a folder called projects on my desktop", "llm_plan", None),
    ("how do magnets work", "llm_plan", None),
    ("charge my phone", "llm_plan", None),

    # ========== CONFLICT / REGRESSION (fullscreen-class bugs) ================
    # fullscreen must NEVER maximize
    ("fullscreen the youtube video", "fullscreen", lambda c: c[1] == (False,)),
    ("make it full screen", "fullscreen", None),
    ("go fullscreen", "fullscreen", None),
    ("full screen", "fullscreen", None),
    ("exit fullscreen", "fullscreen", lambda c: c[1] == (True,)),
    ("minimize the window", "window", lambda c: c[1] == ("minimize",)),
    ("minimize the video", "miniplayer", None),
    ("minimize youtube", "miniplayer", None),
    ("miniplayer", "miniplayer", None),
    ("put the video in miniplayer", "miniplayer", None),
    ("maximize", "window", lambda c: c[1] == ("maximize",)),
    # video pause/mute/next ≠ system media / volume when about youtube/video
    ("pause the video", "ensure_playback", lambda c: c[1] == ("pause",)),
    ("play the video", "ensure_playback", lambda c: c[1] == ("play",)),
    ("stop the video", "ensure_playback", lambda c: c[1] == ("pause",)),
    ("mute the video", "player_key", lambda c: c[1] == ("m",)),
    ("mute youtube", "player_key", lambda c: c[1] == ("m",)),
    ("unmute the video", "player_key", lambda c: c[1] == ("m",)),
    ("next video", "player_key", lambda c: c[1] == ("Shift+N",)),
    ("previous video", "player_key", lambda c: c[1] == ("Shift+P",)),
    ("skip this video", "player_key", lambda c: c[1] == ("Shift+N",)),
    # skip ad ≠ skip song ≠ next video
    ("skip the ad", "skip_ad", None),
    ("skip song", "media", lambda c: c[1] == ("next",)),
    # play Nth must NOT become ensure_playback; on-screen = play_result
    ("play the second video on youtube", "play_result", lambda c: c[1] == (2,)),
    ("play the second video on the youtube homepage", "youtube_home_play", lambda c: c[1] == (2,)),
    ("play the video", "ensure_playback", lambda c: c[1] == ("play",)),
    ("play despacito on youtube", "youtube_search", None),
    # steam ≠ browser
    ("open library in steam", "steam_goto", None),
    ("steam downloads", "steam_goto", None),
    # learn ≠ random read
    ("learn how notepad works", "learn_app", None),
    # small talk ≠ system report
    # (handled as direct reply — expect no system_report call)
]

# Same rules, but YouTube is already open in the controlled browser.
CASES_ON_YT = [
    ("play despacito on youtube", "play_by_title", lambda c: "despacito" in c[1][0]),
    ("play the video called iron man suit up", "play_by_title", lambda c: "iron man" in c[1][0]),
    ("play avengers endgame trailer", "play_by_title", lambda c: "avengers" in c[1][0]),
    ("scroll down", "page_scroll", lambda c: c[1][0] == "down"),
    ("how many videos can you see on screen right now", "list_visible_videos", None),
    ("what videos are on screen", "list_visible_videos", None),
    ("list the videos on youtube", "list_visible_videos", None),
]


def main():
    install_mocks()
    passed, failed = 0, []

    # Special: small-talk must NOT call system_report
    for sentence in ("how are you", "how are you doing"):
        rec.reset()
        reply, _ = brain.handle_command(sentence)
        if rec.called("system_report"):
            failed.append((sentence, "mapped to system_report (should be small talk)"))
        elif not reply or "nominal" not in (reply or "").lower() and "systems" not in (reply or "").lower():
            # accept any non-system-report conversational reply
            if rec.called("llm_plan") or (reply and len(reply) > 5):
                passed += 1
            else:
                failed.append((sentence, f"bad small-talk reply: {reply!r} calls={[c[0] for c in rec.calls]}"))
        else:
            passed += 1

    import app_context

    def _run_cases(cases, *, on_youtube=False):
        nonlocal passed, failed
        for sentence, expected, check in cases:
            if sentence in ("how are you doing",):
                continue
            rec.reset()
            app_context.clear()
            brain.browser._on_youtube = bool(on_youtube)
            if on_youtube:
                app_context.set_app("youtube")
            try:
                reply, acted = brain.handle_command(sentence)
            except Exception as exc:
                failed.append((sentence, f"raised {exc!r}"))
                continue
            if expected == "__STOP_SPEECH__":
                if reply == "__STOP_SPEECH__" and acted:
                    passed += 1
                else:
                    failed.append((sentence, f"expected stop speech, got {reply!r}"))
                continue
            if not rec.called(expected):
                got = [c[0] for c in rec.calls] or ["<nothing>"]
                failed.append((sentence, f"expected {expected}, got {got}"))
                continue
            if check is not None:
                call = rec.first(expected)
                try:
                    ok = check(call)
                except Exception:
                    ok = False
                if not ok:
                    failed.append((sentence, f"{expected} args wrong: {call[1]}, {call[2]}"))
                    continue
            passed += 1

    _run_cases(CASES, on_youtube=False)
    _run_cases(CASES_ON_YT, on_youtube=True)

    total = passed + len(failed)
    print(f"\n=== NEURON rules suite: {passed}/{total} passed ===")
    for sentence, why in failed:
        print(f"FAIL: {sentence!r}\n      {why}")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
