"""JARVIS-style smoke test for NEURON."""
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import brain  # noqa: E402

CASES = [
    "open chrome",
    "close chrome",
    "open youtube",
    "analyze how steam works",
    "scroll down",
    "stop talking",
    "look at monitor 1",
    "what time is it",
    "volume up",
    "exit fullscreen",
    "minimize the video",
    "open steam library",
]


def track(name, bag):
    def f(*a, **k):
        bag.append(name)
        return f"{name} ok"
    return f


def main():
    print("=== 1. HTTP BRAIN ===")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5)
        print("OK", r.status)
    except Exception as e:
        print("FAIL", e)
        return 1

    print("=== 2. OLLAMA ===")
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5).read()
        models = [m.get("name") for m in json.loads(raw).get("models", [])]
        print("OK", ", ".join(models[:6]))
    except Exception as e:
        print("FAIL", e)

    print("=== 3. COMMAND ROUTING (mocked actions) ===")
    bag = []
    brain.actions.open_app = track("open_app", bag)
    brain.actions.close_app = track("close_app", bag)
    brain.actions.scroll = track("scroll", bag)
    brain.actions.volume = track("volume", bag)
    brain.actions.current_time = track("time", bag)
    brain.actions.steam_goto = track("steam_goto", bag)
    brain.app_learner.learn_app = track("learn_app", bag)
    brain.app_learner.learn_website = track("learn_website", bag)
    if brain.vision_agent:
        brain.vision_agent.describe_screens = lambda *a, **k: (
            bag.append("describe_screen") or "Monitor focused."
        )
        brain.vision_agent.is_enabled = lambda: True
        brain.vision_agent.needs_glance = lambda t: False
        brain.vision_agent.quick_screen_context = lambda *a, **k: ""
    if brain.browser:
        brain.browser.fullscreen = lambda exit_fs=False: (bag.append("fullscreen") or "fs")
        brain.browser.miniplayer = lambda: (bag.append("miniplayer") or "mini")
        brain.browser.open_site = lambda u: (bag.append("open_site") or f"open {u}")
        brain._BROWSER = True

    expect = {
        "open chrome": "open_app",
        "close chrome": "close_app",
        "open youtube": "open_site",
        "analyze how steam works": "learn_app",
        "scroll down": "scroll",
        "stop talking": "__STOP_SPEECH__",
        "look at monitor 1": "describe_screen",
        "what time is it": "time",
        "volume up": "volume",
        "exit fullscreen": "fullscreen",
        "minimize the video": "miniplayer",
        "open steam library": "steam_goto",
    }
    passed = 0
    for s in CASES:
        bag.clear()
        reply, acted = brain.handle_command(s)
        want = expect[s]
        ok = False
        if want == "__STOP_SPEECH__":
            ok = reply == "__STOP_SPEECH__" and acted
        else:
            ok = want in bag and acted
        mark = "OK" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"  {mark} {s!r} -> {bag or reply}")
    print(f"ROUTING {passed}/{len(CASES)}")

    print("=== 4. WEBSOCKET ===")
    import websockets

    async def ws():
        async with websockets.connect("ws://127.0.0.1:8765/ws", open_timeout=8) as w:
            msg = json.loads(await asyncio.wait_for(w.recv(), timeout=20))
            print("OK", msg.get("type"), msg.get("backend") or msg.get("engine"),
                  "ready=", msg.get("ready"))

    asyncio.run(ws())
    print("=== JARVIS SMOKE COMPLETE ===")
    return 0 if passed == len(CASES) else 2


if __name__ == "__main__":
    raise SystemExit(main())
