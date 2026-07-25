"""App learning for N.E.U.R.O.N.

When the user says "read this app and learn how it works", NEURON inspects
the foreground (or named) window via UI Automation, asks the reasoning brain
to turn that into usable how-to knowledge, and saves it under app_memory/.

Later commands load that knowledge into the planner so NEURON knows the app's
tabs, buttons, and workflows instead of guessing.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import actions
import brain_llm
import vision

STORE_DIR = Path(__file__).resolve().parent / "app_memory"
STORE_DIR.mkdir(exist_ok=True)

# Built-in deep knowledge we already know — merged into learned files.
KNOWN_SHORTCUTS = {
    "steam": {
        "kind": "desktop_app",
        "name": "Steam",
        "summary": "Steam desktop client for games, store, friends, and downloads.",
        "deep_links": {
            "library": "steam://open/games",
            "store": "steam://open/store",
            "friends": "steam://open/friends",
            "downloads": "steam://open/downloads",
            "community": "steam://open/community",
            "settings": "steam://open/settings",
            "news": "steam://open/news",
        },
        "preferred_action": "steam_goto",
        "notes": (
            "Always use steam_goto / steam_select_account / steam:// deep-links. "
            "Never open Steam in a web browser or Windows Search."
        ),
        "voice_commands": [
            {"say": "open steam", "do": "open_app steam"},
            {"say": "open steam library", "do": "steam_goto library"},
            {"say": "open steam store", "do": "steam_goto store"},
            {"say": "open steam friends", "do": "steam_goto friends"},
            {"say": "open steam downloads", "do": "steam_goto downloads"},
            {"say": "login to the first steam account", "do": "steam_select_account 1"},
            {"say": "open steam settings", "do": "steam_goto settings"},
            {"say": "scroll down", "do": "scroll down in steam"},
            {"say": "scroll up", "do": "scroll up in steam"},
        ],
        "navigation": [
            {"label": "Library", "how": "steam_goto library"},
            {"label": "Store", "how": "steam_goto store"},
            {"label": "Community", "how": "steam_goto community"},
            {"label": "Friends", "how": "steam_goto friends"},
            {"label": "Downloads", "how": "steam_goto downloads"},
        ],
    },
    "notepad": {
        "kind": "desktop_app",
        "preferred_action": "open_app",
        "workflows": [
            {"say": "type text", "steps": ["open_app notepad", "wait", "type_text"]},
            {"say": "save", "steps": ["press_keys control s"]},
        ],
    },
    "chrome": {
        "kind": "browser",
        "notes": "For websites prefer open_website / search_site / play_result — not pixel clicking.",
    },
    "youtube": {
        "kind": "website",
        "preferred_action": "open_website",
        "notes": (
            "YouTube is a WEBSITE in NEURON's controlled browser. "
            "NEVER open_app youtube / Windows Search. "
            "Use open_website youtube, search_site, play_result, youtube_home_play, "
            "play_by_title, skip_ad, ensure_playback, fullscreen, page_scroll, player_key."
        ),
        "voice_commands": [
            {"say": "open youtube", "do": "open_website youtube"},
            {"say": "search X on youtube", "do": "search_site youtube X"},
            {"say": "play the 2nd video on homepage", "do": "youtube_home_play 2"},
            {"say": "come back to youtube home", "do": "youtube_home"},
            {"say": "play the video called iron man", "do": "play_by_title iron man"},
            {"say": "skip the ad", "do": "skip_ad"},
            {"say": "pause the video", "do": "ensure_playback pause"},
            {"say": "play the video", "do": "ensure_playback play"},
            {"say": "fullscreen", "do": "fullscreen"},
            {"say": "scroll down", "do": "page_scroll down"},
            {"say": "mute youtube", "do": "player_key m"},
            {"say": "next video", "do": "player_key Shift+N"},
        ],
        "navigation": [
            {"label": "Home", "how": "open_website youtube"},
            {"label": "Search", "how": "search_site youtube <query>"},
            {"label": "Skip Ad", "how": "skip_ad"},
        ],
    },
}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "app").lower()).strip("-")
    return s[:60] or "app"


def _path_for(slug: str) -> Path:
    return STORE_DIR / f"{slug}.json"


def list_learned() -> list[str]:
    return sorted(p.stem for p in STORE_DIR.glob("*.json"))


def load(slug: str) -> dict | None:
    path = _path_for(_slug(slug))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save(slug: str, data: dict) -> Path:
    path = _path_for(_slug(slug))
    data = dict(data)
    data["slug"] = _slug(slug)
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def knowledge_for_prompt(hint: str = "") -> str:
    """Compact learned-app block for the LLM. Prefer apps mentioned in hint."""
    learned = list_learned()
    if not learned:
        return ""
    hint_l = (hint or "").lower()
    # Prefer apps named in the user request; else include all (capped).
    preferred = [s for s in learned if s in hint_l or any(
        tok and tok in hint_l for tok in s.split("-")
    )]
    order = preferred or learned
    chunks = []
    for slug in order[:4]:
        data = load(slug)
        if not data:
            continue
        lines = [f"LEARNED APP: {data.get('name') or slug}"]
        if data.get("kind"):
            lines.append(f"  kind: {data['kind']}")
        if data.get("summary"):
            lines.append(f"  summary: {data['summary']}")
        if data.get("preferred_action"):
            lines.append(f"  preferred_action: {data['preferred_action']}")
        nav = data.get("navigation") or []
        if nav:
            lines.append("  navigation: " + "; ".join(
                f"{n.get('label')}->{n.get('how')}" for n in nav[:12]
            ))
        cmds = data.get("voice_commands") or []
        if cmds:
            lines.append("  voice_commands:")
            for c in cmds[:10]:
                lines.append(f"    - say \"{c.get('say')}\" => {c.get('do')}")
        if data.get("notes"):
            lines.append(f"  notes: {data['notes']}")
        deep = data.get("deep_links") or {}
        if deep:
            lines.append("  deep_links: " + ", ".join(f"{k}={v}" for k, v in list(deep.items())[:8])
            )
        chunks.append("\n".join(lines))
    if not chunks:
        return ""
    return "LEARNED APP MEMORY (trust this over guessing):\n" + "\n\n".join(chunks)


def _window_info():
    """Foreground window name + process-ish title."""
    try:
        import uiautomation as auto
        root = auto.GetForegroundControl()
        if not root:
            return "", ""
        name = (root.Name or "").strip()
        classname = (root.ClassName or "").strip()
        return name, classname
    except Exception:
        return "", ""


def _fresh_enough(slug: str, hours: float = 24.0) -> bool:
    """True if we already have usable knowledge learned recently."""
    data = load(slug)
    if not data:
        return False
    if not (data.get("voice_commands") or data.get("navigation") or data.get("summary")):
        return False
    try:
        updated = datetime.fromisoformat(data.get("updated", ""))
        age_h = (datetime.now() - updated).total_seconds() / 3600.0
        return age_h < hours
    except Exception:
        return bool(data.get("voice_commands"))


def _focus_app(name: str, open_if_needed: bool = True) -> str:
    """Best-effort: open/focus an app by name before scanning."""
    key = (name or "").strip().lower()
    if not key or key in ("this", "the", "current", "foreground", "it"):
        return "foreground"
    if not open_if_needed:
        return key
    # Websites must never go through open_app / Windows Search.
    if key in getattr(actions, "WEB_SERVICES", {}) or key in ("yt", "youtube"):
        return key
    # Steam: use the real Steam window focus helper (not Start Menu / taskbar).
    if "steam" in key:
        ok = actions._focus_steam()
        time.sleep(1.0)
        return "steam" if ok else "steam"
    # Don't schedule another auto-learn while we're already learning.
    actions.open_app(key, auto_learn=False)
    time.sleep(2.0)
    try:
        actions._focus_window_by_title(key)
    except Exception:
        pass
    return key


def _is_junk_scan(title: str, classname: str, elements: list) -> bool:
    """True if we accidentally scanned the taskbar / desktop / NEURON."""
    tl = (title or "").lower()
    cl = (classname or "").lower()
    if any(x in tl for x in (
        "taskbar", "n.e.u.r.o.n", "neuron", "program manager",
        "windows default lock", "start",
    )):
        return True
    if "shell_traywnd" in cl or "traywnd" in cl:
        return True
    # Taskbar-ish control names dominate the scan.
    names = " ".join((e.get("name") or "").lower() for e in (elements or [])[:20])
    junk_hits = sum(1 for w in (
        "show desktop", "show hidden icons", "clock ", "volume ",
        "network ", "battery", "running window",
    ) if w in names)
    return junk_hits >= 3


def _parse_json_loose(raw: str) -> dict:
    """Parse model JSON; tolerate markdown fences / trailing junk."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty JSON")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def _is_website_target(name: str) -> bool:
    key = (name or "").strip().lower()
    if key in ("yt", "youtube"):
        return True
    try:
        return key in actions.WEB_SERVICES
    except Exception:
        return False


def _scan_ui(max_elements: int = 90) -> tuple[str, str, list]:
    title, classname = _window_info()
    elements = vision.capture_elements(max_elements=max_elements, time_budget=6.0)
    return title, classname, elements


def _vision_screen_notes(goal_hint: str = "") -> str:
    """Optional multimodal pass: describe visible UI when UIA is thin."""
    try:
        import vision_agent
        if not vision_agent.is_enabled():
            return ""
        import screen_capture as sc
        shots = sc.capture_all_monitors()
        cfg = vision_agent._load_config()
        model = (cfg.get("vision") or {}).get("model", "qwen2.5vl:7b")
        client = vision_agent._get_client()
        content = [{
            "type": "text",
            "text": (
                "Describe this desktop for a voice assistant. "
                "List main windows per monitor, tabs, buttons, and what the user can do. "
                "Be concise (8-12 short bullets). App hint: "
                f"{goal_hint or 'foreground'}."
            ),
        }]
        for shot in shots[:3]:
            b64 = sc.encode_jpeg(shot["image"], quality=55, max_w=1024)
            content.append({"type": "text", "text": shot["label"]})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
            max_tokens=400,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[app_learner] vision notes failed: {exc}", flush=True)
        return ""


LEARN_SYSTEM = """You are documenting how a Windows desktop app OR website works for a voice assistant.
Return STRICT JSON only (no markdown):
{
  "name": "<short name>",
  "kind": "desktop_app|website|browser|other",
  "summary": "<2 short sentences>",
  "navigation": [{"label":"<tab/button>","how":"<tool or click>"}],
  "voice_commands": [{"say":"<phrase>","do":"<NEURON tool recipe>"}],
  "preferred_action": "<steam_goto|open_app|open_website|search_site|youtube_home_play|computer_use|none>",
  "notes": "<critical do/don't>"
}
Rules:
- For YouTube/websites: prefer open_website / search_site / play_by_title / play_result / youtube_home_play /
  skip_ad / ensure_playback / fullscreen / page_scroll. NEVER open_app or Windows Search.
- For Steam: steam_goto / steam_select_account.
- Include 5-12 short voice_commands.
"""

LEARN_WEB_SYSTEM = """You are documenting how a WEBSITE works for a voice assistant that drives a controlled browser.
You get the live page URL, title, and on-page labels from the page currently under control.
Return STRICT JSON only (no markdown):
{
  "name": "<site name>",
  "kind": "website",
  "summary": "<2 short sentences about this page/site>",
  "navigation": [{"label":"<control>","how":"<how to use NEURON tools on it>"}],
  "voice_commands": [{"say":"<phrase>","do":"<tool recipe>"}],
  "preferred_action": "open_website",
  "notes": "<critical: always use controlled browser tools, never Windows Search>"
}
For YouTube always include: open_website, search_site, youtube_home_play, play_by_title, play_result,
skip_ad, ensure_playback, fullscreen, page_scroll, player_key.
"""


def learn_website(
    site: str = "youtube",
    *,
    auto: bool = False,
    force: bool = False,
) -> str:
    """Learn a website from NEURON's controlled browser page — never Windows Search."""
    if not brain_llm.is_enabled():
        return "" if auto else "My reasoning core is offline, so I can't learn sites right now."

    key = (site or "youtube").strip().lower()
    if key == "yt":
        key = "youtube"
    if key in ("this", "the", "current", "it", "page", "site", ""):
        key = ""

    try:
        import browser as br
        if not br.supported():
            return "" if auto else "Browser control isn't available to learn this website."
    except Exception:
        return "" if auto else "Browser control isn't available to learn this website."

    slug = _slug(key or "website")
    if key == "youtube":
        slug = "youtube"
    refresh_h = 24.0
    try:
        cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
        refresh_h = float((cfg.get("auto_learn") or {}).get("refresh_hours", 24))
    except Exception:
        pass
    if auto and not force and slug != "website" and _fresh_enough(slug, refresh_h):
        return f"Already know {slug}."

    try:
        # If already on YouTube and user said "this"/youtube, don't navigate away.
        hint = key
        if not hint:
            try:
                if br.on_youtube():
                    hint = "youtube"
            except Exception:
                pass
        snap = br.learn_snapshot(hint)
    except Exception as exc:
        return "" if auto else f"I couldn't read the controlled browser page: {exc}"

    url = snap.get("url") or ""
    title = snap.get("title") or ""
    labels = snap.get("labels") or []
    listing = "\n".join(f"- {x}" for x in labels[:60])
    site_name = key or ("youtube" if "youtube.com" in url.lower() else (title.split("-")[0].strip() or "website"))

    user_blob = (
        f"Site hint: {site_name}\n"
        f"Live URL: {url}\n"
        f"Page title: {title}\n"
        f"On-page controls/labels:\n{listing or '(none)'}\n"
        "Document how to control THIS live page with NEURON browser tools."
    )

    data = None
    try:
        raw = brain_llm.chat_json([
            {"role": "system", "content": LEARN_WEB_SYSTEM},
            {"role": "user", "content": user_blob},
        ], timeout=90)
        data = _parse_json_loose(raw)
    except Exception as exc:
        print(f"[app_learner] website LLM parse failed: {exc}", flush=True)
        data = {
            "name": site_name.title() if site_name != "youtube" else "YouTube",
            "kind": "website",
            "summary": f"Live page under control: {title or url}.",
            "navigation": [{"label": x, "how": f"click_text '{x}'"} for x in labels[:12]],
            "voice_commands": [],
            "preferred_action": "open_website",
            "notes": "Learned from controlled browser DOM (LLM JSON failed).",
        }

    # Merge known website recipes (especially YouTube).
    known_key = "youtube" if ("youtube" in site_name.lower() or "youtube.com" in url.lower()) else site_name.lower()
    if known_key in KNOWN_SHORTCUTS:
        known = KNOWN_SHORTCUTS[known_key]
        for k, v in known.items():
            if k not in data or not data[k]:
                data[k] = v
            elif k == "voice_commands" and isinstance(v, list):
                # Prefer known recipes; keep extras from model
                merged = list(v) + [c for c in (data.get("voice_commands") or []) if c not in v]
                data["voice_commands"] = merged[:14]
        slug = known_key
        data["name"] = "YouTube" if known_key == "youtube" else data.get("name") or known_key
        data["kind"] = "website"

    data["window_title_sample"] = title
    data["url_sample"] = url
    data["control_count"] = len(labels)
    data["top_controls"] = [{"name": x, "role": "web"} for x in labels[:40]]
    data["learned_from"] = "controlled_browser"
    if auto:
        data["auto"] = True

    path = save(slug, data)
    cmd_n = len(data.get("voice_commands") or [])
    spoken = f"Done. I learned how {data.get('name', slug)} works from the page under my control"
    if cmd_n:
        spoken += f" — {cmd_n} voice patterns"
    spoken += ". I'll control it with browser tools, not Windows Search."
    print(f"[app_learner] website saved {path}", flush=True)
    if auto:
        return f"Learned {data.get('name', slug)}."
    return spoken


def learn_app(
    target: str = "",
    *,
    auto: bool = False,
    open_if_needed: bool = True,
    force: bool = False,
) -> str:
    """Inspect an app/site and persist how-to knowledge. Returns a spoken reply.

    auto=True  -> quiet background learn (when an app opens); skip if fresh.
    open_if_needed=False -> only scan whatever is already in the foreground.
    """
    if not brain_llm.is_enabled():
        return "" if auto else "My reasoning core is offline, so I can't learn apps right now."

    hint = (target or "").strip()
    hint_key = hint.lower()

    # Websites (YouTube, Gmail, …) — learn from controlled browser, NEVER Win search.
    if _is_website_target(hint_key) or hint_key in (
        "this page", "this site", "current page", "the page",
    ):
        if hint_key in ("this page", "this site", "current page", "the page", "this", "current"):
            site = ""
        elif hint_key == "yt":
            site = "youtube"
        else:
            site = hint_key
        return learn_website(site, auto=auto, force=force)

    # If user said "learn this" and controlled browser is on YouTube, learn the site.
    if hint_key in ("", "this", "the", "current", "foreground", "it"):
        try:
            import browser as br
            if br.supported() and br.on_youtube():
                return learn_website("youtube", auto=auto, force=force)
        except Exception:
            pass
    # Guess slug early to skip redundant auto-learns.
    early_slug = _slug(
        hint if hint_key not in ("", "this", "the", "current", "foreground", "it")
        else "app"
    )
    for known in KNOWN_SHORTCUTS:
        if known in early_slug or known in hint_key:
            early_slug = known
            break
    refresh_h = 24.0
    try:
        import json as _json
        from pathlib import Path as _P
        cfg = _json.loads((_P(__file__).parent / "config.json").read_text(encoding="utf-8"))
        refresh_h = float((cfg.get("auto_learn") or {}).get("refresh_hours", 24))
    except Exception:
        pass
    if auto and not force and early_slug != "app" and _fresh_enough(early_slug, refresh_h):
        return f"Already know {early_slug}."

    if open_if_needed and not auto:
        focused = _focus_app(target, open_if_needed=True)
        time.sleep(0.6)
    else:
        focused = "foreground"
        time.sleep(0.3)

    title, classname, elements = _scan_ui()
    # If we landed on the taskbar / NEURON / desktop, refocus and rescan once.
    if _is_junk_scan(title, classname, elements):
        print(f"[app_learner] junk scan ({title!r}) — refocusing {hint_key or focused}", flush=True)
        if "steam" in (hint_key or focused or ""):
            actions._focus_steam()
            time.sleep(1.2)
        elif hint_key and hint_key not in ("this", "foreground", ""):
            actions._focus_window_by_title(hint_key)
            time.sleep(1.0)
        title, classname, elements = _scan_ui()
        if _is_junk_scan(title, classname, elements):
            # Still junk — for known apps, save recipe-only knowledge instead of garbage UI.
            known_key = None
            for k in KNOWN_SHORTCUTS:
                if k in (hint_key or "") or k in (focused or ""):
                    known_key = k
                    break
            if known_key and known_key in KNOWN_SHORTCUTS:
                data = dict(KNOWN_SHORTCUTS[known_key])
                data["learned_from"] = "builtin_recipes_focus_failed"
                data["notes"] = (
                    (data.get("notes") or "")
                    + " UI scan missed the main window; using built-in control recipes."
                ).strip()
                path = save(known_key, data)
                try:
                    import app_context
                    app_context.set_app(known_key)
                except Exception:
                    pass
                print(f"[app_learner] saved builtin recipes {path}", flush=True)
                return (
                    f"I focused {data.get('name', known_key)} and loaded how to control it "
                    f"({len(data.get('voice_commands') or [])} voice patterns). "
                    f"Try: scroll down, open steam store, open steam library."
                )
            return "" if auto else (
                "I couldn't get the app's main window in front (I saw the taskbar instead). "
                "Click the app once, then say analyze again."
            )

    if not elements and not title:
        return "" if auto else (
            "I couldn't see any app UI to learn from. Bring the app to the front and ask again."
        )

    listing = vision.elements_as_text(elements)
    hint_name = target.strip() if target and target.lower() not in (
        "this", "the", "current", "foreground", "it", ""
    ) else (title.split("-")[0].split("—")[0].strip() if title else focused)

    # Skip auto-learn for empty shells / our own UI.
    tl = (title or "").lower()
    if auto and any(x in tl for x in ("n.e.u.r.o.n", "neuron brain", "program manager")):
        return ""

    # Chrome/Edge showing YouTube → learn as website from controlled browser.
    if "youtube" in tl or "youtube" in (hint_name or "").lower():
        return learn_website("youtube", auto=auto, force=force)

    slug_guess = _slug(hint_name)
    for known in KNOWN_SHORTCUTS:
        if known in slug_guess or known in hint_name.lower() or known in tl:
            slug_guess = known
            break
    if auto and not force and _fresh_enough(slug_guess, refresh_h):
        return f"Already know {slug_guess}."

    vision_notes = ""
    use_vision = len(elements) < 8
    try:
        import json as _json
        from pathlib import Path as _P
        acfg = (_json.loads((_P(__file__).parent / "config.json").read_text(encoding="utf-8"))
                .get("auto_learn") or {})
        if acfg.get("vision_on_sparse", True) is False:
            use_vision = False
    except Exception:
        pass
    if use_vision:
        vision_notes = _vision_screen_notes(hint_name or title)

    user_blob = (
        f"App hint: {hint_name}\n"
        f"Window title: {title or '(unknown)'}\n"
        f"Class: {classname or '(unknown)'}\n"
        f"Controls:\n{listing or '(none readable)'}\n"
    )
    if vision_notes:
        user_blob += f"\nVision/OCR screen notes:\n{vision_notes}\n"

    try:
        raw = brain_llm.chat_json([
            {"role": "system", "content": LEARN_SYSTEM},
            {"role": "user", "content": user_blob},
        ], timeout=90)
        data = _parse_json_loose(raw)
    except Exception as exc:
        # Structural fallback: still save raw controls so future commands have something.
        print(f"[app_learner] LLM parse failed: {exc}", flush=True)
        if elements:
            data = {
                "name": hint_name or title or "app",
                "kind": "desktop_app",
                "summary": f"Scanned UI of {title or hint_name}.",
                "navigation": [
                    {"label": e["name"], "how": f"click '{e['name']}'"}
                    for e in elements if e.get("name") and e.get("clickable")
                ][:15],
                "voice_commands": [],
                "preferred_action": "computer_use",
                "notes": f"Learned from UI scan only (LLM JSON failed: {exc}).",
                "auto": bool(auto),
            }
        else:
            return "" if auto else f"I scanned the app but couldn't turn it into knowledge: {exc}"

    name = (data.get("name") or hint_name or "app").strip()
    slug = _slug(name)
    for known_key, known in KNOWN_SHORTCUTS.items():
        if known_key in slug or known_key in name.lower() or known_key in tl:
            for k, v in known.items():
                if k not in data or not data[k]:
                    data[k] = v
                elif k == "deep_links" and isinstance(v, dict):
                    merged = dict(v)
                    merged.update(data.get("deep_links") or {})
                    data["deep_links"] = merged
                elif k == "voice_commands" and isinstance(v, list):
                    # Prefer known control recipes; keep extras from scan.
                    merged = list(v) + [
                        c for c in (data.get("voice_commands") or []) if c not in v
                    ]
                    data["voice_commands"] = merged[:16]
            slug = known_key
            data["name"] = known_key.title() if known_key != "chrome" else "Chrome"
            break

    data["window_title_sample"] = title
    data["control_count"] = len(elements)
    data["top_controls"] = [
        {"name": e.get("name"), "role": e.get("role")}
        for e in elements[:40]
        if e.get("name")
    ]
    if auto:
        data["auto"] = True

    path = save(slug, data)
    try:
        import app_context
        app_context.set_app(slug)
    except Exception:
        pass
    nav_n = len(data.get("navigation") or [])
    cmd_n = len(data.get("voice_commands") or [])
    summary = (data.get("summary") or "").strip()
    spoken = f"Done. I learned how {data.get('name', slug)} works"
    if cmd_n:
        spoken += f" - {cmd_n} voice patterns"
    if nav_n:
        spoken += f", {nav_n} navigation points"
    spoken += ". I'll keep controlling this app for your next commands."
    if summary and "taskbar" not in summary.lower():
        spoken += " " + summary.split(".")[0].strip() + "."
    print(f"[app_learner] saved {path} (auto={auto})", flush=True)
    if auto:
        return f"Learned {data.get('name', slug)}."
    return spoken


def recall_summary(name: str) -> str:
    data = load(name)
    if not data:
        # fuzzy
        for slug in list_learned():
            if name.lower() in slug or slug in name.lower():
                data = load(slug)
                break
    if not data:
        return f"I haven't learned {name} yet. Open it and say learn this app."
    bits = [f"I know {data.get('name') or name}."]
    if data.get("summary"):
        bits.append(data["summary"])
    cmds = data.get("voice_commands") or []
    if cmds:
        examples = ", ".join(f"\"{c.get('say')}\"" for c in cmds[:3] if c.get("say"))
        if examples:
            bits.append(f"Try saying {examples}.")
    return " ".join(bits)
