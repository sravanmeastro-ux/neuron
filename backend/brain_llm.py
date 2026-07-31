"""N.E.U.R.O.N reasoning layer — turns any request into a plan of actions.

Provider-agnostic: works with any OpenAI-compatible endpoint (OpenAI cloud,
or a fully-local model via Ollama / LM Studio). Configured in config.json.

plan(request, context) -> dict:
    {
      "say": "spoken reply",
      "steps": [ {"action": "open_app", "args": {"name": "chrome"}}, ... ]
    }
Returns None if the LLM is disabled or unavailable (caller falls back to rules).
"""

import json
import urllib.request
from pathlib import Path

import app_knowledge
import skills

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# Model families that support (and default to) thinking — we turn it off for
# planning: a voice assistant needs fast, strict-JSON answers.
_THINK_FAMILIES = ("qwen3", "deepseek-r1", "gpt-oss", "magistral")

# Compact tool card — keep short for voice latency.
TOOLS_DOC = """
ACTIONS (only these):
open_app{name} | close_app{name} | steam_goto{section} | steam_select_account{index,name?}
discord_friends{} | open_settings{page?} | replay_clicks{id?,say?} | learn_app{name} | train_pc{deep_learn?} | training_status{} | stop_training{}
open_website{site,browser?} | search_site{site,query} | search_web{query}
youtube_home{} | youtube_home_play{index} | play_by_title{title} | play_result{index,where?} | list_visible_videos{} | skip_ad{}
fullscreen{exit?} | player_key{key} | ensure_playback{want:play|pause}
click_text{text} | page_scroll{direction:up|down} | scroll{direction}
type_text{text} | press_keys{keys} | click{button?,double?}
move_mouse{direction,amount?} | volume{action} | media{action}
window{action} | screenshot{all?} | describe_screen{request?} | create_folder{name,location?}
create_file{name,content?,location?} | open_folder{location}
run_shell{command} | wait{seconds} | system_report{} | computer_use{goal}
RULES: websites→open_website/search_site (not open_app). Steam tabs→steam_goto.
"open friends chat" / Discord DMs→discord_friends. Steam friends→steam_goto{section:friends}.
Windows Settings→open_settings{page}. Google→open_website/search_site. Opera/Blender/WhatsApp/Notepad→open_app.
Teach mouse workflows→user says start recording clicks, then stop recording / remember that as …
OR research tutorials→"learn from youtube how to X" / "ask google how to X" (saves recipes from captions/snippets).
replay_clicks for saved click recipes. NEVER silently record all clicks forever.
Steam login / "first account" / "Who's playing"→steam_select_account — NEVER search_web,
NEVER open_app with a long phrase (that opens Windows Search / Bing).
"learn my computer"→train_pc (inventory all apps; prefer deep_learn false unless user wants deep).
"analyze/learn how steam works"→learn_app (ONE app). NEVER auto-scan every focused window.
Unknown UI / click that→computer_use.
"what's on my screen(s)"→describe_screen. "click that / on my other screen"→computer_use.
"close chrome/notepad"→close_app (NEVER click_text Close). close tab→press_keys control w.
fullscreen video→fullscreen (never window maximize). minimize the video→miniplayer (never window minimize).
exit fullscreen→fullscreen{exit}. skip ad / skip add / skip sad→skip_ad ONLY (never page_scroll / browser_scroll / click random Skip in comments).
play Nth on YT home→youtube_home_play. Go/come back to YT home→youtube_home (NEVER play). Play by visible title→play_by_title. How many/what videos on screen→list_visible_videos (NEVER play_result). Prefer 1 step. computer_use for in-app UI / visual deixis.
When LIVE SCREENS context is present, use it — don't invent what's open.
NEVER use search_web / Windows Start for desktop control ("open X account", "click…").
Use PC INVENTORY app names with open_app when present.
"""

SYSTEM_PROMPT = """You are {name}, a Windows desktop voice AI.
Personality: {personality}
The user speaks normally and simply (e.g. "open chrome", "close chrome", "pause the video").
They do NOT need to say your name — hands-free. Understand plain English. Do not invent fancy interpretations.
Reply with STRICT JSON only:
{{"say":"<short spoken reply>","steps":[{{"action":"<name>","args":{{...}}}}]}}
- Empty steps only for pure chat.
- Never claim success in say without the step that does it.
- New request = new task; don't repeat the last action unless asked.
- Prefer the SIMPLEST matching skill. Don't overcomplicate short asks.

{tools}

{skills}

{app_knowledge}
"""

_client = None
_cfg = None


def _load_config():
    global _cfg
    if _cfg is None:
        try:
            _cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cfg = {}
    return _cfg


def reload_config():
    global _cfg, _client
    _cfg = None
    _client = None
    return _load_config()


def is_enabled() -> bool:
    llm = _load_config().get("llm", {})
    return bool(llm.get("enabled") and llm.get("api_key"))


def _get_client():
    global _client
    if _client is not None:
        return _client
    from openai import OpenAI
    llm = _load_config()["llm"]
    _client = OpenAI(base_url=llm["base_url"], api_key=llm["api_key"])
    return _client


def warmup():
    """Load the model into memory so the first real request isn't slow."""
    if not is_enabled():
        return
    try:
        client = _get_client()
        llm = _load_config()["llm"]
        client.chat.completions.create(
            model=llm["model"],
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            timeout=120,
            extra_body=_extra_body(llm["model"]),
        )
    except Exception:
        pass


def _extra_body(model: str) -> dict:
    extra = {"keep_alive": -1}
    if model.startswith(_THINK_FAMILIES):
        extra["think"] = False
    return extra


def _native_base():
    """Ollama's native API base (supports think:false), else None."""
    base = _load_config().get("llm", {}).get("base_url", "")
    if "11434" in base or "ollama" in base.lower():
        return base.split("/v1")[0].rstrip("/")
    return None


def _plan_options(llm: dict) -> dict:
    """Tight generation limits so planning stays voice-snappy."""
    return {
        "temperature": float(llm.get("temperature", 0.1)),
        "num_predict": int(llm.get("num_predict", 220)),
        "num_ctx": int(llm.get("num_ctx", 4096)),
    }


def chat_json(messages, model: str = None, timeout: int = None) -> str:
    """One strict-JSON chat completion.

    Uses Ollama's native API locally so thinking can actually be disabled
    (the OpenAI-compatible endpoint ignores the switch — measured 3-5x slower).
    Falls back to the OpenAI-compatible client for any other provider.
    """
    llm = _load_config()["llm"]
    mdl = model or llm["model"]
    timeout = int(timeout if timeout is not None else llm.get("timeout_seconds", 25))
    native = _native_base()
    if native:
        opts = _plan_options(llm)
        body = {
            "model": mdl,
            "messages": messages,
            "format": "json",
            "stream": False,
            "keep_alive": -1,
            "options": opts,
        }
        if mdl.startswith(_THINK_FAMILIES):
            body["think"] = False
        req = urllib.request.Request(
            native + "/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["message"]["content"]

    resp = _get_client().chat.completions.create(
        model=mdl,
        messages=messages,
        temperature=_plan_options(llm)["temperature"],
        max_tokens=_plan_options(llm)["num_predict"],
        response_format={"type": "json_object"},
        timeout=timeout,
        extra_body=_extra_body(mdl),
    )
    return resp.choices[0].message.content


def plan(request: str, context: str = "", model: str = None, normalized: str = ""):
    if not is_enabled():
        return None

    cfg = _load_config()
    llm = cfg["llm"]
    assistant = cfg.get("assistant", {})
    mdl = model or llm["model"]
    tools = TOOLS_DOC
    try:
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        # Registry is source of truth; keep RULES trailer from TOOLS_DOC
        rules_tail = TOOLS_DOC.split("RULES:", 1)[-1] if "RULES:" in TOOLS_DOC else ""
        tools = tool_registry.tools_doc()
        if rules_tail:
            tools = tools + "\nRULES:" + rules_tail
        # Prefer UIA over coords
        tools += (
            "\nPrefer get_ui_tree/find_ui_element/click_ui_element over click/move_mouse. "
            "Coordinate clicking is last resort only."
        )
    except Exception:
        pass
    system = SYSTEM_PROMPT.format(
        name=assistant.get("name", "NEURON"),
        personality=assistant.get("personality", "witty, concise"),
        tools=tools,
        skills=skills.for_prompt(),
        app_knowledge=app_knowledge.for_prompt(),
    )

    messages = [{"role": "system", "content": system}]
    if context:
        # Cap context so memory/history can't balloon latency.
        ctx = context.strip()
        if len(ctx) > 1800:
            ctx = ctx[-1800:]
        messages.append({"role": "system", "content": "Context:\n" + ctx})
    user_blob = request
    if normalized and normalized.strip().lower() != (request or "").strip().lower():
        user_blob = (
            f"User said: {request}\n"
            f"Normalized intent (prefer this): {normalized}"
        )
    messages.append({"role": "user", "content": user_blob})

    try:
        raw = chat_json(messages, model=mdl)
        data = json.loads(raw)
        if "steps" not in data:
            data["steps"] = []
        return data
    except Exception as exc:
        return {"say": f"My reasoning core had a problem: {exc}", "steps": []}
