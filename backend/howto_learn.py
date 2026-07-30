"""Learn workflows from Google / YouTube tutorials — not only user click recording.

Flow:
  1) Search Google (and/or YouTube) for "how to <goal>"
  2) Pull snippets + optional YouTube captions
  3) Ask the local LLM to turn that into NEURON actions / click targets
  4) Save into app_memory + voice_recipes

Voice examples:
  "learn from youtube how to open discord friends"
  "ask google how to render in blender"
  "train from google and youtube how to use whatsapp desktop"
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parent / "app_memory"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get(url: str, timeout: float = 12.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _strip_html(html: str) -> str:
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = re.sub(r"(?is)<[^>]+>", " ", t)
    t = unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def search_google(query: str, limit: int = 5) -> list[dict]:
    """Best-effort Google HTML scrape for titles + snippets."""
    q = urllib.parse.quote_plus(f"how to {query}" if "how to" not in query.lower() else query)
    url = f"https://www.google.com/search?q={q}&hl=en&num={limit}"
    try:
        html = _get(url)
    except Exception as exc:
        return [{"title": "google_error", "snippet": str(exc), "url": ""}]

    results = []
    # Classic result blocks
    for m in re.finditer(
        r'<a href="(/url\?q=([^\"&]+)[^"]*)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
        html,
        re.I | re.S,
    ):
        href = urllib.parse.unquote(m.group(2))
        title = _strip_html(m.group(3))
        if href.startswith("http") and title:
            results.append({"title": title[:160], "url": href.split("&")[0], "snippet": ""})
        if len(results) >= limit:
            break

    # Snippets
    snippets = re.findall(
        r'<div[^>]*class="[^"]*(?:VwiC3b|yDYNvb|s3v9rd)[^"]*"[^>]*>(.*?)</div>',
        html,
        re.I | re.S,
    )
    for i, sn in enumerate(snippets[:limit]):
        text = _strip_html(sn)[:320]
        if i < len(results):
            results[i]["snippet"] = text
        elif text:
            results.append({"title": "", "url": "", "snippet": text})

    if not results:
        # DuckDuckGo HTML fallback
        try:
            ddg = _get(f"https://html.duckduckgo.com/html/?q={q}")
            for m in re.finditer(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
                ddg,
                re.I | re.S,
            ):
                href = unescape(m.group(1))
                if "uddg=" in href:
                    try:
                        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        href = urllib.parse.unquote(qs.get("uddg", [href])[0])
                    except Exception:
                        pass
                results.append({
                    "title": _strip_html(m.group(2))[:160],
                    "url": href,
                    "snippet": _strip_html(m.group(3))[:320],
                })
                if len(results) >= limit:
                    break
        except Exception as exc:
            results.append({"title": "ddg_error", "snippet": str(exc), "url": ""})
    return results[:limit]


def search_youtube(query: str, limit: int = 4) -> list[dict]:
    """YouTube search page → video ids + titles."""
    q = urllib.parse.quote_plus(f"how to {query}" if "how to" not in query.lower() else query)
    url = f"https://www.youtube.com/results?search_query={q}"
    try:
        html = _get(url, timeout=15)
    except Exception as exc:
        return [{"title": "youtube_error", "video_id": "", "snippet": str(exc)}]

    vids = []
    # ytInitialData often embeds videoRenderer blocks
    for m in re.finditer(
        r'"videoId":"([a-zA-Z0-9_-]{11})".{0,400}?"title":\{"runs":\[\{"text":"(.*?)"\}',
        html,
    ):
        vid, title = m.group(1), unescape(m.group(2).encode("utf-8").decode("unicode_escape", errors="ignore"))
        title = re.sub(r"\\u0026", "&", title)
        if any(v.get("video_id") == vid for v in vids):
            continue
        vids.append({
            "title": title[:160],
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "snippet": "",
        })
        if len(vids) >= limit:
            break

    if not vids:
        # Simpler fallback
        for m in re.finditer(r"watch\?v=([a-zA-Z0-9_-]{11})", html):
            vid = m.group(1)
            if any(v.get("video_id") == vid for v in vids):
                continue
            vids.append({
                "title": f"youtube:{vid}",
                "video_id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "snippet": "",
            })
            if len(vids) >= limit:
                break
    return vids[:limit]


def youtube_captions(video_id: str, max_chars: int = 3500) -> str:
    """Fetch auto/manual English captions when available."""
    if not video_id:
        return ""
    try:
        html = _get(f"https://www.youtube.com/watch?v={video_id}", timeout=15)
    except Exception:
        return ""

    # captionTracks JSON
    m = re.search(r'"captionTracks":(\[.*?\])\s*,\s*"audioTracks"', html)
    if not m:
        m = re.search(r'"captionTracks":(\[.*?\])', html)
    if not m:
        # description as weak fallback
        d = re.search(r'"shortDescription":"(.*?)"', html)
        if d:
            desc = unescape(d.group(1).encode("utf-8").decode("unicode_escape", errors="ignore"))
            desc = desc.replace("\\n", "\n")
            return desc[:max_chars]
        return ""

    try:
        tracks = json.loads(m.group(1))
    except Exception:
        return ""

    base = ""
    for t in tracks:
        lang = (t.get("languageCode") or "").lower()
        if lang.startswith("en"):
            base = t.get("baseUrl") or ""
            break
    if not base and tracks:
        base = tracks[0].get("baseUrl") or ""
    if not base:
        return ""

    try:
        xml = _get(base + "&fmt=srv3", timeout=12)
    except Exception:
        try:
            xml = _get(base, timeout=12)
        except Exception:
            return ""

    texts = re.findall(r"<text[^>]*>(.*?)</text>", xml, re.I | re.S)
    joined = " ".join(_strip_html(t) for t in texts)
    return joined[:max_chars]


def _guess_app(goal: str) -> str:
    g = (goal or "").lower()
    mapping = [
        ("discord", "discord"),
        ("youtube", "youtube"),
        ("google", "google"),
        ("opera", "opera"),
        ("steam", "steam"),
        ("blender", "blender"),
        ("notepad", "notepad"),
        ("whatsapp", "whatsapp"),
        ("settings", "windows-settings"),
        ("windows", "windows-settings"),
    ]
    for needle, slug in mapping:
        if needle in g:
            return slug
    words = re.findall(r"[a-z0-9]+", g)
    return words[0] if words else "workflow"


def _llm_extract(goal: str, evidence: str) -> dict:
    import brain_llm

    system = (
        "You convert web/YouTube how-to text into NEURON desktop recipes. "
        "Reply STRICT JSON only."
    )
    user = f"""
Goal the user wants NEURON to learn: {goal}

Evidence from Google/YouTube (may be noisy):
{evidence[:6000]}

Return JSON:
{{
  "app": "<short app slug>",
  "summary": "<1 sentence>",
  "voice_commands": [
    {{"say":"<short spoken phrase>","do":"<NEURON tool recipe like open_app discord / discord_friends / press_keys control k / computer_use: ...>"}}
  ],
  "click_targets": [
    {{"label":"<UI name>","where":"<region>","do":"<action or keys>"}}
  ],
  "workflows": [
    {{"say":"<phrase>","steps":["step1","step2"]}}
  ],
  "preferred_action": "<open_app|open_website|discord_friends|steam_goto|open_settings|computer_use|press_keys>"
}}
Rules:
- Prefer real NEURON tools when known: discord_friends, steam_goto, open_settings, open_website, search_site, youtube_home, press_keys, type_text, computer_use.
- Keep 4-10 voice_commands, short say phrases.
- If evidence is weak, still give best-effort Windows/desktop steps.
"""
    raw = brain_llm.chat_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        timeout=45,
    )
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    if not isinstance(data, dict):
        data = {}
    return data


def _save_knowledge(app: str, goal: str, data: dict, sources: list[dict]) -> Path:
    import app_learner

    slug = app_learner._slug(app or _guess_app(goal))
    existing = app_learner.load(slug) or {}
    merged = dict(existing)
    merged["name"] = merged.get("name") or slug
    merged["kind"] = merged.get("kind") or "desktop_app"
    merged["summary"] = data.get("summary") or merged.get("summary") or f"Learned how-to: {goal}"
    merged["preferred_action"] = data.get("preferred_action") or merged.get("preferred_action") or "computer_use"
    merged["learned_from"] = "howto_web"
    merged["howto_goal"] = goal
    merged["howto_sources"] = [
        {"title": s.get("title"), "url": s.get("url")} for s in sources[:8]
    ]
    merged["updated_howto"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Merge lists
    for key in ("voice_commands", "click_targets", "workflows", "navigation"):
        incoming = data.get(key) or []
        if not isinstance(incoming, list):
            continue
        prev = list(merged.get(key) or [])
        for item in incoming:
            if item and item not in prev:
                prev.append(item)
        merged[key] = prev[:16]

    notes = (merged.get("notes") or "").strip()
    extra = f"Web/YouTube how-to for: {goal}."
    if extra not in notes:
        merged["notes"] = (notes + " " + extra).strip()

    return app_learner.save(slug, merged)


def _save_voice_recipes(data: dict, app: str) -> int:
    import voice_recipes

    n = 0
    for cmd in (data.get("voice_commands") or [])[:10]:
        say = (cmd.get("say") or "").strip()
        do = (cmd.get("do") or "").strip()
        if len(say) < 3 or not do:
            continue
        action, args = _parse_do(do, app)
        if not action:
            continue
        voice_recipes.remember(say, action, args, app=app)
        n += 1
    return n


def _parse_do(do: str, app: str) -> tuple[str, dict]:
    d = do.strip()
    low = d.lower()

    if low.startswith("discord_friends"):
        return "discord_friends", {}
    if low.startswith("youtube_home"):
        return "youtube_home", {}
    m = re.match(r"steam_goto\s+(\w+)", low)
    if m:
        return "steam_goto", {"section": m.group(1)}
    m = re.match(r"open_settings(?:\s+(\w+))?", low)
    if m:
        return "open_settings", {"page": m.group(1) or "home"}
    m = re.match(r"open_app(?:\s+\{?name[=:]?\s*)?([a-z0-9 ._-]+)", low)
    if m:
        return "open_app", {"name": m.group(1).strip(" {}")}
    if low.startswith("open_app"):
        return "open_app", {"name": app}
    m = re.match(r"open_website(?:\s+\{?site[=:]?\s*)?([a-z0-9 ._-]+)", low)
    if m:
        return "open_website", {"site": m.group(1).strip(" {}")}
    m = re.match(r"search_site\s+(\w+)\s+(.+)$", low)
    if m:
        return "search_site", {"site": m.group(1), "query": m.group(2).strip()}
    m = re.match(r"press_keys?\s+(.+)$", low)
    if m:
        keys = m.group(1).replace("+", " ").replace(",", " ")
        return "press_keys", {"keys": keys}
    if "computer_use" in low:
        goal = re.sub(r"^.*computer_use\s*:?\s*", "", d, flags=re.I).strip() or d
        return "computer_use", {"goal": goal}
    # Fallback: treat whole string as computer_use goal
    return "computer_use", {"goal": d}


def learn_howto(
    goal: str,
    *,
    use_google: bool = True,
    use_youtube: bool = True,
    app: str = "",
) -> str:
    """Research goal online and install recipes into NEURON memory."""
    goal = (goal or "").strip()
    if len(goal) < 3:
        return "Tell me what to learn, e.g. 'learn from youtube how to open discord friends'."

    sources: list[dict] = []
    evidence_parts: list[str] = []

    if use_google:
        g = search_google(goal)
        sources.extend(g)
        evidence_parts.append("GOOGLE RESULTS:")
        for i, r in enumerate(g, 1):
            evidence_parts.append(
                f"{i}. {r.get('title','')}\n{r.get('snippet','')}\n{r.get('url','')}"
            )

    if use_youtube:
        y = search_youtube(goal)
        sources.extend(y)
        evidence_parts.append("\nYOUTUBE RESULTS:")
        for i, r in enumerate(y, 1):
            evidence_parts.append(f"{i}. {r.get('title','')} — {r.get('url','')}")
        # Captions from top 2 videos
        for r in y[:2]:
            vid = r.get("video_id") or ""
            caps = youtube_captions(vid)
            if caps:
                evidence_parts.append(
                    f"\nCAPTIONS from {r.get('title','video')}:\n{caps}"
                )

    evidence = "\n".join(evidence_parts).strip()
    if len(evidence) < 40:
        return (
            "I couldn't get useful Google/YouTube results (network blocked or empty). "
            "Try again, or say 'start recording clicks' to teach me manually."
        )

    try:
        data = _llm_extract(goal, evidence)
    except Exception as exc:
        # Offline LLM — still store raw research notes
        data = {
            "app": app or _guess_app(goal),
            "summary": f"Collected web/YouTube notes for: {goal} (LLM offline: {exc})",
            "voice_commands": [],
            "click_targets": [],
            "workflows": [
                {"say": goal, "steps": ["computer_use: " + goal]},
            ],
            "preferred_action": "computer_use",
        }

    slug = (app or data.get("app") or _guess_app(goal)).strip().lower()
    path = _save_knowledge(slug, goal, data, sources)
    n_voice = _save_voice_recipes(data, slug)

    # Also bind the raw goal phrase → computer_use / preferred action
    try:
        import voice_recipes
        pref = (data.get("preferred_action") or "computer_use").strip()
        if pref == "computer_use":
            voice_recipes.remember(goal, "computer_use", {"goal": goal}, app=slug)
        elif pref == "discord_friends":
            voice_recipes.remember(goal, "discord_friends", {}, app=slug)
        elif pref.startswith("open_"):
            action, args = _parse_do(pref + " " + slug, slug)
            voice_recipes.remember(goal, action, args, app=slug)
        else:
            voice_recipes.remember(goal, "computer_use", {"goal": goal}, app=slug)
    except Exception:
        pass

    cmds = data.get("voice_commands") or []
    samples = ", ".join(f'\"{c.get("say")}\"' for c in cmds[:3] if c.get("say"))
    src_n = len([s for s in sources if s.get("title") and "error" not in (s.get("title") or "")])
    return (
        f"Learned from the web how to: {goal}. "
        f"Saved to {path.name} ({len(cmds)} voice patterns, {n_voice} recipes, "
        f"{src_n} sources). "
        + (f"Try saying {samples}." if samples else "Say the goal anytime and I'll try those steps.")
    )


def learn_from_utterance(text: str) -> str | None:
    """Parse a spoken request; return reply or None if not a howto-learn ask."""
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    use_yt = bool(re.search(r"\byoutube\b|\bvideo(?:s)?\b|\btutorial\b", t))
    use_g = bool(re.search(r"\bgoogle\b|\bweb\b|\bonline\b|\bsearch\b", t))
    # Default both if they say "learn from the internet / train from tutorials"
    if re.search(r"\b(internet|online|tutorials?|web)\b", t):
        use_yt = use_g = True
    if not use_yt and not use_g:
        # "learn how to X from youtube" already sets use_yt; bare "ask google" sets use_g
        if not re.search(r"\b(ask google|from google|from youtube|learn from|train from)\b", t):
            return None
        use_g = True

    # Extract the goal after how to / how /
    m = re.search(
        r"(?:ask google|from youtube|from google|learn from(?: youtube| google| the web| online)?|"
        r"train from(?: youtube| google| tutorials?)?|watch(?: a)?(?: youtube)?(?: video)?(?: on| about)?|"
        r"search(?: google| youtube)?(?: for| how to)?)\s+(.+)$",
        t,
    )
    goal = ""
    if m:
        goal = m.group(1).strip()
    if not goal:
        m2 = re.search(r"\bhow to (.+)$", t)
        if m2:
            goal = m2.group(1).strip()
    goal = re.sub(r"^(how to|to)\s+", "", goal).strip()
    goal = re.sub(r"\b(from youtube|from google|on youtube|on google|please)$", "", goal).strip()
    if len(goal) < 3:
        return None

    # If only one source named, disable the other
    if re.search(r"\bfrom youtube\b|\bon youtube\b|\byoutube video\b", t) and not re.search(r"\bgoogle\b", t):
        use_g = False
        use_yt = True
    if re.search(r"\bfrom google\b|\bask google\b|\bon google\b", t) and not re.search(r"\byoutube\b", t):
        use_yt = False
        use_g = True

    return learn_howto(goal, use_google=use_g or not use_yt, use_youtube=use_yt or not use_g)
