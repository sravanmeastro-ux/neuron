"""N.E.U.R.O.N brain — turns spoken sentences into actions.

handle_command(text) -> (reply: str | None, acted: bool)
Returns reply=None when the sentence doesn't match any command
(so random conversation doesn't trigger anything).
"""

import json
import re

import actions
import app_learner
import brain_llm
import memory
import nlu
import stt

try:
    import browser
    _BROWSER = browser.supported()
except Exception:
    browser = None
    _BROWSER = False

try:
    import vision_agent
except Exception:
    vision_agent = None

# Per-turn multi-screen glance (mode 1B: before almost every command).
_LAST_SCREEN_CTX = ""


def _refresh_screen_glance(text: str, *, force_vlm: bool = False) -> str:
    """Glance at all monitors; cache on module for this turn / LLM context."""
    global _LAST_SCREEN_CTX
    if not vision_agent or not vision_agent.is_enabled():
        _LAST_SCREEN_CTX = ""
        return ""
    try:
        if force_vlm or vision_agent.needs_glance(text):
            _LAST_SCREEN_CTX = vision_agent.quick_screen_context(
                text, force_vlm=force_vlm
            )
        else:
            _LAST_SCREEN_CTX = ""
    except Exception as exc:
        print(f"[brain] screen glance failed: {exc}", flush=True)
        _LAST_SCREEN_CTX = ""
    return _LAST_SCREEN_CTX

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "1st": 1, "2nd": 2, "3rd": 3,
}


def _parse_ordinal(word: str):
    word = word.strip().lower()
    if word in ORDINALS:
        return ORDINALS[word]
    m = re.match(r"(\d+)", word)
    return int(m.group(1)) if m else None


def _web_open(site: str, browser_name: str = "") -> str:
    """Open a site in NEURON's controlled browser if possible, else the default.

    Always prefer the controlled Playwright Chrome so later commands
    (play/scroll/skip ad/learn) can act on the SAME session.
    """
    site_key = (site or "").strip().lower()
    if _BROWSER:
        msg = browser.open_site(actions._resolve_site_url(site_key or site))
        # Soft-learn youtube/site in background from the live page.
        try:
            if site_key in ("youtube", "yt") or "youtube" in site_key:
                try:
                    import app_context
                    app_context.set_app("youtube")
                except Exception:
                    pass
                import threading
                import app_learner

                def _bg():
                    try:
                        app_learner.learn_website("youtube", auto=True, force=False)
                    except Exception:
                        pass
                threading.Thread(target=_bg, daemon=True, name="learn-yt").start()
        except Exception:
            pass
        return msg
    return actions.open_website(site, browser_name)


def _youtube_active() -> bool:
    """True when NEURON's Chrome is already on YouTube (or last focus was YT)."""
    try:
        import app_context
        if app_context.get_app() == "youtube":
            return True
    except Exception:
        pass
    if not _BROWSER:
        return False
    try:
        return bool(browser.on_youtube())
    except Exception:
        return False


def _strip_youtube_tail(phrase: str) -> str:
    s = (phrase or "").strip()
    s = re.sub(
        r"\s+(?:on|in|from)\s+(?:the\s+)?"
        r"(?:youtube|yt)(?:\s+(?:home(?:\s*page)?|homepage|home\s*feed|feed))?$",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(
        r"\s+(?:on|in|from)\s+(?:the\s+)?"
        r"(?:home(?:\s*page)?|homepage|home\s*feed|feed)$",
        "",
        s,
        flags=re.I,
    )
    return s.strip(" .,!?'\"")


def _web_search(site: str, query: str, browser_name: str = "") -> str:
    key = site.strip().lower()
    if _BROWSER:
        if key in ("youtube", "yt"):
            try:
                import app_context
                app_context.set_app("youtube")
            except Exception:
                pass
            return browser.youtube_search(query)
        import urllib.parse
        template = actions.SITE_SEARCH.get(key)
        if template:
            return browser.search(template.format(q=urllib.parse.quote(query)),
                                   f"Searching {site} for {query}.")
        return browser.open_site(actions._resolve_site_url(key))
    return actions.search_site(site, query, browser_name)


# Common speech-recognition mishears live in nlu.MISHEARS (single source).


def _fix_mishears(text: str) -> str:
    return nlu._apply_pairs(text, nlu.MISHEARS)


def _clean(text: str) -> str:
    """Normalize speech for rule matching (delegates to NLU)."""
    return nlu.clean(text)


def handle_command(raw: str):
    # NLU: turn casual / messy speech into a short simple intent first.
    _nlu = nlu.understand(raw)
    text = _nlu["canonical"] or _nlu["cleaned"]
    if _nlu.get("rewrote"):
        print(f"[nlu] '{_nlu['cleaned']}' -> '{text}'", flush=True)
    if not text:
        return None, False

    # ---- stop talking (TTS barge-in) ---------------------------------
    if re.search(
        r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron)\b",
        text,
    ):
        return "__STOP_SPEECH__", True

    # ---- monitor focus: look at / use monitor N ---------------------
    m_focus = re.search(
        r"\b(?:look at|see|watch|use|focus on|listen to|work on)\s+"
        r"(?:my\s+|the\s+)?monitor\s*(one|two|1|2|first|second)\b"
        r"|\bmonitor\s*(one|two|1|2|first|second)\b",
        text,
    )
    if m_focus:
        import monitor_focus
        word = (m_focus.group(1) or m_focus.group(2) or "1").lower()
        mid = 1 if word in ("1", "one", "first") else 2
        # Set focus, then briefly describe THAT monitor only.
        monitor_focus.set_focus(mid)
        if vision_agent and vision_agent.is_enabled():
            desc = vision_agent.describe_screens(
                f"monitor {mid} only", monitor_id=mid
            )
            # Keep spoken reply short; focus stickiness does the rest.
            short = (desc or "").replace("\n", " ")
            if len(short) > 220:
                short = short[:200].rsplit(" ", 1)[0] + "."
            return (
                f"Focusing on monitor {mid}. {short} "
                f"Say what to do — I'll use monitor {mid}."
            ), True
        return monitor_focus.set_focus(mid), True

    if re.search(
        r"\b(stop focusing|clear focus|all monitors|both monitors|"
        r"watch all screens)\b",
        text,
    ):
        import monitor_focus
        return monitor_focus.clear_focus(), True

    # Mode 1B: glance at screens before almost every command (structural always;
    # VLM when the user refers to on-screen stuff).
    _refresh_screen_glance(text)

    # ---- multi-screen describe (see + understand) --------------------
    if vision_agent and vision_agent.is_enabled() and re.search(
        r"\bwhat(?:'s| is|s) on (?:my |the )?(?:screen|screens|monitor|monitors|display|displays)\b"
        r"|\bdescribe (?:my |the )?(?:screen|screens|monitor|monitors|desktop|display)s?\b"
        r"|\blook at (?:my |the )?(?:screen|screens|monitor|monitors)\b"
        r"|\bcan you see (?:my |the )?(?:screen|screens|desktop)\b",
        text,
    ):
        return vision_agent.describe_screens(text), True

    # ---- general vision computer-use (any app / any monitor) ---------
    m = re.match(
        r"(?:take control|control the screen|use your eyes|use vision|"
        r"look at the screen and|on screen|do it yourself|"
        r"click (?:on )?that|do that|press that|"
        r"on (?:my |the )?(?:other|second|left|right) (?:screen|monitor))\b"
        r"[, ]*(?:to |and )?(.+)?",
        text,
    )
    if m and vision_agent and vision_agent.is_enabled():
        goal = (m.group(1) or text).strip() or text
        return vision_agent.computer_use(goal), True

    # Deictic / visual goals without an explicit "take control" prefix
    if vision_agent and vision_agent.is_enabled() and re.search(
        r"\b(click|press|select|open|close|scroll|type)\b.+\b"
        r"(that|this|here|there|on (?:the |my )?(?:screen|monitor|display))\b"
        r"|\b(on|using) (?:my |the )?(?:other|second|left|right) (?:screen|monitor)\b",
        text,
    ):
        return vision_agent.computer_use(text), True

    # ---- PC-wide training (inventory apps + folders in background) ----
    if re.search(
        r"\b(learn|study|train|map|inventory|scan)\b.+\b(computer|pc|laptop|system|machine)\b"
        r"|\b(learn|study|train)\b.+\b(every|all|each)\b.+\b(app|application|program|folder)s?\b"
        r"|\blearn (every|all) (app|folder)s?\b"
        r"|\btrain (yourself|your brain|on my (pc|computer))\b"
        r"|\bmap my (pc|computer|apps|folders)\b",
        text,
    ):
        import pc_trainer
        deep = not re.search(r"\b(quick|fast|inventory only|just (scan|map|inventory))\b", text)
        return pc_trainer.start_training(deep_learn=deep), True

    if re.search(
        r"\b(training status|learn(?:ing)? status|what have you learned"
        r"|how much have you learned|pc (map|inventory) status)\b",
        text,
    ):
        import pc_trainer
        return pc_trainer.status_report(), True

    if re.search(r"\b(stop|cancel) (training|learning|pc (scan|map))\b", text):
        import pc_trainer
        return pc_trainer.stop_training(), True

    # ---- learn / read a single app -----------------------------------
    # "learn/analyze/study how steam works", "read this app"
    # (do NOT catch "learn every app" / "learn my computer" — handled above)
    if re.search(
        r"\b(learn|study|read|memorize|remember how|analy[sz]e|inspect|figure out|"
        r"understand|teach yourself|memorise)\b",
        text,
    ) and re.search(
        r"\b(app|application|program|software|how (it|this|that) works|how .+ works|"
        r"how .+ (?:is|are) (?:used|controlled)|controls?|ui|interface)\b",
        text,
    ) and not re.search(r"\b(every|all|each|computer|pc|laptop|machine)\b", text):
        # Pull a target app name if present.
        m = re.search(
            r"(?:learn|study|read|memorize|analy[sz]e|inspect|understand|figure out|"
            r"teach yourself|memorise)\s+(?:how\s+)?(?:the\s+)?([a-z0-9 .]+?)\s+"
            r"(?:app|application|program)?\s*(?:works|and learn|and memorize)?$",
            text,
        )
        target = ""
        if m:
            target = m.group(1).strip()
            target = re.sub(r"^(how|the|this|that)\s+", "", target).strip()
        if not target:
            m2 = re.search(
                r"\b(steam|notepad|chrome|spotify|discord|word|excel|code|cursor|"
                r"youtube|yt|gmail|maps|netflix|github)\b",
                text,
            )
            if m2:
                target = m2.group(1)
        if not target and re.search(r"\b(this|the|current)\s+(app|window|program|page|site)\b", text):
            target = "this"
        # YouTube / websites → controlled browser learn (never Win search)
        if (target or "").lower() in ("youtube", "yt") or (
            target and target.lower() in actions.WEB_SERVICES
        ):
            return app_learner.learn_website(
                "youtube" if (target or "").lower() in ("youtube", "yt") else target,
                force=True,
            ), True
        return app_learner.learn_app(target or "this", force=True), True

    if re.match(r"what do you know about (.+)", text):
        return app_learner.recall_summary(re.match(r"what do you know about (.+)", text).group(1)), True

    # ---- Steam desktop client (NEVER the web browser / Windows Search) ----
    if re.search(r"\bsteam\b", text) and not re.search(
        r"\b(learn|study|read|analy[sz]e|inspect|understand|figure out|memorize|teach)\b",
        text,
    ):
        # Login / pick saved account on "Who's playing?" — NEVER open_app / Win search.
        if re.search(r"\b(account|login|log in|sign in|who's playing|who is playing)\b", text):
            # Only capture an explicit name ("login as Bob", "account named X")
            m_name = re.search(
                r"(?:log(?: ?in)|sign in)(?: as| with| to) ([a-z0-9_.\-]{2,40})"
                r"|(?:account (?:named|called)) ([a-z0-9_.\-]{2,40})"
                r"|\bas ([a-z0-9_.\-]{2,40})(?: on| in) steam\b",
                text,
            )
            name = ""
            if m_name:
                name = next(g for g in m_name.groups() if g)
                name = re.sub(r"\b(steam|account|the)\b", " ", name)
                name = re.sub(r"\s+", " ", name).strip()
            ordinal_m = re.search(
                r"\b(\d+|first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\b",
                text,
            )
            n = _parse_ordinal(ordinal_m.group(1)) if ordinal_m else 1
            return actions.steam_select_account(n or 1, name), True

        for section in (
            "library", "games", "store", "community", "friends",
            "downloads", "settings", "news", "inventory", "profile",
        ):
            if re.search(rf"\b{section}\b", text):
                return actions.steam_goto(section), True
        # Bare "open steam" falls through to the generic open rule below.

    # ---- YouTube: skip ad (MUST be before play-video rules) ----------
    # Speech often hears "ad" as "add" / "sad".
    if _BROWSER and re.search(
        r"\b(skip|close|dismiss)\b.{0,20}\b(ad|ads|add|adds|sad)\b"
        r"|\b(ad|ads|add|adds|sad)\b.{0,12}\b(skip|close|dismiss)\b",
        text,
    ):
        return browser.skip_ad(), True

    # ---- YouTube home ONLY (never play) -----------------------------
    # "come back to youtube home screen" must NOT become youtube_home_play.
    if _BROWSER and re.search(
        r"\b(?:come\s+back|go\s+back|return|take\s+me\s+back|back)\s+to\s+(?:the\s+)?"
        r"(?:youtube|yt)\b.*\b(?:home(?:\s*(?:page|screen))?|homepage|feed)\b"
        r"|\b(?:come\s+back|go\s+back|return|take\s+me\s+back|back)\s+to\s+(?:the\s+)?"
        r"(?:home(?:\s*(?:page|screen))?|homepage|feed)\b"
        r"|\b(?:go\s+to|open|show|visit)\s+(?:the\s+)?(?:youtube|yt)\s+"
        r"(?:home(?:\s*(?:page|screen))?|homepage|feed)\b"
        r"|\b(?:youtube|yt)\s+(?:home(?:\s*(?:page|screen))?|homepage)\b$",
        text,
    ) and not re.search(
        r"\b(?:play|watch|start)\b.+\b(?:video|result|first|second|third|\d+)",
        text,
    ):
        try:
            import app_context
            app_context.set_app("youtube")
        except Exception:
            pass
        return browser.youtube_home(), True

    # YouTube player controls (only when clearly about the video/youtube —
    # never steal generic "next song" / system mute).
    if _BROWSER and re.search(r"\b(youtube|yt|video|videos)\b", text):
        if re.search(r"\b(next video|skip (this |the )?video|play next)\b", text):
            return browser.player_key("Shift+N"), True
        if re.search(r"\b(previous video|last video|play previous)\b", text):
            return browser.player_key("Shift+P"), True
        if re.search(r"\b(mute|unmute)\b", text) and not re.search(r"\bvolume\b", text):
            return browser.player_key("m"), True
        # Absolute play/pause for the CURRENT video only — not "play X on youtube".
        if re.fullmatch(
            r"(?:pause|stop)(?: the)?(?: (?:youtube )?(?:video|it))?", text
        ) or re.search(r"\b(pause|stop) (?:the )?(?:youtube )?video\b", text):
            return browser.ensure_playback("pause"), True
        if re.fullmatch(
            r"(?:play|resume|unpause)(?: the)?(?: (?:youtube )?(?:video|it))?", text
        ) or re.search(r"\b(play|resume|unpause) (?:the )?(?:youtube )?video\b", text):
            # Don't steal "play the 2nd video" or "play the video called <title>"
            if not re.search(
                r"\b(\d+|first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)\b",
                text,
            ) and not re.search(r"\b(called|named|titled)\b", text):
                # "play the video X..." (title after) is not resume-current
                if not re.search(
                    r"\b(?:play|resume|unpause) (?:the )?(?:youtube )?video\s+\S+",
                    text,
                ):
                    return browser.ensure_playback("play"), True
        if re.search(r"\b(captions|subtitles)\b", text):
            return browser.player_key("c"), True

    # ---- act inside the page: "play the 2nd video / result" ----------
    # Default = Nth video CURRENTLY VISIBLE on screen (after scroll counts).
    # Only force homepage navigation when they explicitly say homepage/home feed
    # AND are not pointing at the screen ("on screen", "i can see").
    _on_screen = bool(re.search(
        r"\b(?:on\s+(?:my\s+|the\s+)?screen|i\s+can\s+see|that\s+i\s+see|"
        r"visible|showing|in\s+(?:my\s+|the\s+)?view)\b",
        text,
    ))
    m = re.match(
        r"(?:play|open|click|select|watch|start)(?: the)? "
        r"(\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd)"
        r"(?:st|nd|rd|th)? (?:video|result|one|link|song|item)"
        r"(?:\s+(?:on|in|from|that|i|which)\b.*)?$",
        text,
    )
    if not m:
        # Loose: "play second video on screen" / "play 2nd video i can see"
        m = re.search(
            r"\b(?:play|open|click|select|watch|start)\b.+\b"
            r"(\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
            r"1st|2nd|3rd|4th|5th)\b.+\b(?:video|result|one)\b",
            text,
        )
    if m:
        n = _parse_ordinal(m.group(1))
        if n and _BROWSER:
            want_home = (
                not _on_screen
                and re.search(r"\b(home\s*page|homepage|home\s*feed|home\s*screen)\b", text)
            )
            # "on youtube" alone still means current YouTube view (scrolled feed OK).
            if want_home:
                return browser.youtube_home_play(n), True
            return browser.play_result(n), True
        if not _BROWSER:
            return "Browser control isn't available right now.", True

    # Fuzzy speech: "...second video...youtube..." even when words are jumbled.
    # Do NOT fire this for skip-ad / "not this video" / complaints.
    if (
        _BROWSER
        and re.search(r"\b(video|videos)\b", text)
        and (
            re.search(r"\b(youtube|yt)\b", text)
            or _on_screen
            or _youtube_active()
        )
        and not re.search(r"\b(skip|ad|ads|add|not this|wrong|stop|don't|dont)\b", text)
    ):
        ordinal_m = re.search(
            r"\b(\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
            r"1st|2nd|3rd|4th|5th)\b",
            text,
        )
        wants_play = re.search(r"\b(play|open|click|select|watch|start)\b", text)
        if ordinal_m and wants_play:
            n = _parse_ordinal(ordinal_m.group(1))
            if n:
                if (
                    not _on_screen
                    and re.search(r"\b(home\s*page|homepage|home\s*feed)\b", text)
                ):
                    return browser.youtube_home_play(n), True
                return browser.play_result(n), True

    # ---- play by on-screen title (not ordinal) --------------------------
    # "play iron man suit up", "play the video called …", "watch … on youtube"
    # when YouTube is already open — match visible feed titles via the page DOM.
    if _BROWSER and re.search(r"\b(play|watch|start)\b", text) and not re.search(
        r"\b(\d+|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\b",
        text,
    ):
        title_q = None
        m = re.match(
            r"(?:play|watch|start|open)(?: the)? video(?: called| named| titled) (.+)$",
            text,
        )
        if m:
            title_q = _strip_youtube_tail(m.group(1))
        if not title_q:
            m = re.match(
                r"(?:play|watch|start)(?: the)?(?: video)?(?: called| named| titled) (.+)$",
                text,
            )
            if m:
                title_q = _strip_youtube_tail(m.group(1))
        if not title_q:
            m = re.match(
                r"(?:play|watch|start)(?: for)? (.+?)(?: (?:on|in|from) "
                r"(youtube|yt)(?: (?:in|on|using) "
                r"(chrome|google chrome|edge|microsoft edge|firefox|brave))?)?$",
                text,
            )
            if m:
                title_q = _strip_youtube_tail(m.group(1))
        ban = {
            "", "video", "videos", "it", "this", "that", "them",
            "song", "music", "next", "previous", "last", "ad", "ads",
        }
        if title_q and title_q.lower() not in ban and len(title_q) >= 2:
            explicit = bool(re.search(r"\b(called|named|titled)\b", text))
            mentions_yt = bool(re.search(r"\b(youtube|yt)\b", text))
            on_yt = _youtube_active()
            # On YouTube already → match visible titles. Explicit "called/named"
            # always uses title match. Otherwise "play X on youtube" searches.
            if explicit or on_yt:
                try:
                    import app_context
                    app_context.set_app("youtube")
                except Exception:
                    pass
                return browser.play_by_title(title_q), True
            if mentions_yt:
                # Not on YT yet — fall through to site search below.
                pass

    # "click on <something>" inside the current page
    m = re.match(r"click(?: on)? the (.+)", text)
    if m and _BROWSER and len(m.group(1)) > 2:
        return browser.click_text(m.group(1).strip()), True

    # ---- web: site-specific search (must come before generic search) -
    # "search/play/find/watch X on youtube", optionally "... in chrome"
    m = re.match(
        r"(?:search|find|look up|play|watch|show me)(?: for)? (.+?) (?:on|in|from) "
        r"(youtube|yt|youtube music|google maps|google|maps|amazon|flipkart|spotify|github|wikipedia)"
        r"(?: (?:in|on|using) (chrome|google chrome|edge|microsoft edge|firefox|brave))?$",
        text,
    )
    if m:
        return _web_search(m.group(2), m.group(1), m.group(3) or ""), True

    # "on youtube search X" / "youtube search X"
    m = re.match(
        r"(?:on |in )?(youtube|yt|google maps|google|amazon|flipkart|spotify|github|wikipedia) "
        r"(?:search|find|play|for|look up) (?:for )?(.+)",
        text,
    )
    if m:
        return _web_search(m.group(1), m.group(2)), True

    # ---- web: open a site, optionally in a specific browser ----------
    # "open X in chrome" / "open youtube on edge"
    m = re.match(
        r"(?:open|launch|start|go to) (?:the )?(?:website |site )?(.+?) "
        r"(?:in|on|using|with) (?:the )?(chrome|google chrome|edge|microsoft edge|firefox|brave|browser)$",
        text,
    )
    if m:
        return _web_open(m.group(1).strip(), m.group(2)), True

    m = re.match(r"(?:open|launch|start) (?:the )?website (.+)", text)
    if m:
        return _web_open(m.group(1)), True

    m = re.match(r"(?:search|google)(?: for)? (.+)", text)
    if m:
        if _BROWSER:
            import urllib.parse
            return browser.search(
                "https://www.google.com/search?q=" + urllib.parse.quote(m.group(1)),
                f"Searching for {m.group(1)}."), True
        return actions.search_web(m.group(1)), True

    # ---- open: decide app vs website / special folders ---------------
    # Normal speech: "open chrome", "open the chrome", "open google chrome"
    m = re.match(r"(?:open|launch|start|go to) (.+)", text)
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(?:the|my|a|an)\s+", "", target, flags=re.I).strip()
        target = re.sub(r"^google\s+(chrome)\b", r"\1", target, flags=re.I).strip()
        target_key = target.lower()
        # "go to desktop" = show desktop, not open a folder named desktop
        if target_key in ("desktop", "the desktop"):
            return actions.window("desktop"), True
        # Known user folders
        if target_key in (
            "downloads", "documents", "docs", "pictures", "music", "videos",
            "my downloads", "my documents", "my pictures",
        ):
            loc = target_key.replace("my ", "")
            if loc == "docs":
                loc = "documents"
            return actions.open_folder(loc), True
        # explicit domain or www
        if re.search(r"\.(com|org|net|in|io|dev|gov|edu)\b", target) or target.startswith("www"):
            return _web_open(target), True
        # Websites FIRST (youtube/gmail/…) — never treat as desktop apps / Win search
        # "youtube home" / "youtube homepage" → site home, not open_app
        if re.match(
            r"^(?:youtube|yt)(?:\s+home(?:\s*(?:page|screen))?|\s+homepage|\s+feed)?$",
            target_key,
        ):
            try:
                import app_context
                app_context.set_app("youtube")
            except Exception:
                pass
            if _BROWSER and re.search(r"home|feed", target_key):
                return browser.youtube_home(), True
            return _web_open("youtube"), True
        if target_key in actions.WEB_SERVICES or target_key in ("yt",):
            return _web_open(target), True
        # Strip "in chrome" leftovers already handled above; bare site names
        m_site = re.match(
            r"(.+?)(?:\s+(?:in|on|using|with)\s+(?:the\s+)?(?:chrome|google chrome|edge|browser))?$",
            target_key,
        )
        site_only = (m_site.group(1) if m_site else target_key).strip()
        if site_only in actions.WEB_SERVICES:
            return _web_open(site_only), True
        # real desktop app we know about
        if target_key in actions.APPS:
            return actions.open_app(target), True
        # Command-like phrases must NOT hit Windows Search via open_app —
        # hand them to the reasoning brain / computer_use instead.
        if actions._looks_like_command_phrase(target_key) or len(target_key.split()) > 3:
            if brain_llm.is_enabled():
                result = _run_with_llm(raw, normalized=text)
                if result is not None:
                    return result
            if vision_agent and vision_agent.is_enabled():
                return vision_agent.computer_use(raw), True
            return (
                "That sounds like a task, not an app name. Try being more specific, "
                "e.g. 'open steam' or 'login to the first steam account'."
            ), True
        # Short unknown app name — resolve exe / Start Menu
        return actions.open_app(target), True

    # ---- typing & keys ----------------------------------------------
    # "type X" / "write down X" = literal dictation. Creative asks like
    # "write a poem in notepad" must go to the reasoning brain instead.
    m = re.match(r"(?:type|write down) (.+)", text)
    if m and not re.match(r"(?:a|an|some) ", m.group(1)):
        return actions.type_text(m.group(1)), True

    m = re.match(r"(?:press|hit) (.+)", text)
    if m:
        return actions.press_keys(m.group(1)), True

    # ---- mouse -------------------------------------------------------
    if re.fullmatch(r"(?:mouse )?double click", text):
        return actions.click(double=True), True
    if re.fullmatch(r"(?:mouse )?right click", text):
        return actions.click(button="right"), True
    if re.fullmatch(r"(?:mouse )?(?:left )?click", text):
        return actions.click(), True

    m = re.match(r"(?:move )?(?:the )?mouse (up|down|left|right)(?: by (\d+))?", text)
    if m:
        amount = int(m.group(2)) if m.group(2) else 200
        return actions.move_mouse(m.group(1), amount), True

    if "mouse" in text and ("center" in text or "middle" in text):
        return actions.mouse_to_center(), True

    # Scroll — focus the app we're controlling (Steam etc.), not NEURON itself.
    m = re.search(
        r"\bscroll(?:ing)?\s+(?:the\s+)?(?:page\s+)?(up|down)\b"
        r"|\b(up|down)\s+scroll\b"
        r"|\bscroll(?:ing)?\s+(?:on\s+)?(?:youtube|yt|chrome|browser|page|steam|app)\s+(up|down)\b"
        r"|\b(?:youtube|yt|page|feed|steam)\b.*\bscroll(?:ing)?\s+(up|down)\b"
        r"|\bscroll(?:ing)?\s+(up|down)\s+(?:on\s+)?(?:youtube|yt|chrome|browser|page|feed|steam)\b",
        text,
    )
    if m:
        direction = next(g for g in m.groups() if g)
        import app_context
        mentions_yt = bool(re.search(
            r"\b(youtube|yt|page|feed|browser|chrome|site|results)\b", text
        ))
        # Bare "scroll down" while controlling YouTube → scroll the feed, not Steam/NEURON.
        use_page = (
            _BROWSER
            and not re.search(r"\bsteam\b", text)
            and (mentions_yt or _youtube_active() or app_context.get_app() == "youtube")
        )
        if use_page:
            try:
                app_context.set_app("youtube")
            except Exception:
                pass
            return browser.page_scroll(direction), True
        # Prefer explicit steam, else last controlled app, else foreground focus scroll.
        target = ""
        if re.search(r"\bsteam\b", text):
            target = "steam"
        else:
            target = app_context.get_app()
            # If Steam window is already open/front, treat bare scroll as Steam.
            if not target:
                try:
                    if actions._steam_window():
                        title, _ = __import__("app_learner", fromlist=["_window_info"])._window_info()
                        if "steam" in (title or "").lower():
                            target = "steam"
                        elif actions._steam_window():
                            # Steam is open even if NEURON is focused — user likely means it.
                            target = "steam"
                except Exception:
                    pass
        return actions.scroll(direction, app=target), True

    # Bare "scroll youtube" / "scroll the feed" → down
    if _BROWSER and re.search(r"\bscroll(?:ing)?\b", text) and re.search(
        r"\b(youtube|yt|feed|page|results)\b", text
    ):
        direction = "up" if re.search(r"\bup\b", text) else "down"
        try:
            import app_context
            app_context.set_app("youtube")
        except Exception:
            pass
        return browser.page_scroll(direction), True

    # ---- volume & media -----------------------------------------------
    if re.search(r"volume up|increase (?:the )?volume|louder", text):
        return actions.volume("up"), True
    if re.search(r"volume down|decrease (?:the )?volume|quieter|lower (?:the )?volume", text):
        return actions.volume("down"), True
    # System mute ONLY when not clearly about a video/youtube (those use player 'm').
    if re.search(r"\b(mute|unmute)\b", text) and not re.search(r"\b(youtube|yt|video|videos)\b", text):
        return actions.volume("mute"), True

    # Bare play/pause toggles media. "play despacito" is a REQUEST for content
    # and must fall through to the reasoning brain (search + play).
    if re.fullmatch(
        r"(?:play|pause|resume|stop)(?: the)?(?: (?:music|song|track|media|it))?",
        text,
    ):
        return actions.media("playpause"), True
    if re.search(r"next (track|song)|skip (?:this |the |a )?(song|track)", text):
        return actions.media("next"), True
    if re.search(r"previous (track|song)|last song", text):
        return actions.media("previous"), True

    # ---- windows ------------------------------------------------------
    # "close chrome" / "quit notepad" / "exit steam" — NEVER click_text "Close"
    m = re.match(
        r"(?:close|quit|exit)(?: the| my| a)? (.+)",
        text,
    )
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(?:the|my|a|an)\s+", "", target, flags=re.I).strip()
        target = re.sub(r"^google\s+(chrome)\b", r"\1", target, flags=re.I).strip()
        # Don't steal ads, or "exit fullscreen" / minimize / maximize.
        steal = re.search(r"\b(ad|ads|add|adds|sad)\b", target) or re.search(
            r"\b(full\s*screen|fullscreen|minimi[sz]e|maximi[sz]e)\b", text
        )
        if not steal:
            if re.fullmatch(r"(?:window|app|application|program)", target):
                return actions.window("close"), True
            if re.fullmatch(r"tab", target) or target.endswith(" tab"):
                return actions.press_keys("control w"), True
            # Named app: close chrome, close notepad, quit spotify...
            return actions.close_app(target), True

    if re.search(r"close (?:the |this )?(window|app|tab)", text):
        if "tab" in text:
            return actions.press_keys("control w"), True
        return actions.window("close"), True

    # VIDEO miniplayer ≠ WINDOW minimize.
    # "minimize the video" / "miniplayer" → YouTube 'i', NEVER shrink Chrome.
    if _BROWSER and (
        re.search(r"\b(mini\s*player|miniplayer|picture[\s-]?in[\s-]?picture|\bpip\b)\b", text)
        or (
            re.search(r"minimi[sz]e", text)
            and re.search(r"\b(video|youtube|yt|player)\b", text)
        )
        or re.search(
            r"\b(shrink|small|smaller|pop\s*out)\b.+\b(video|youtube|yt|player)\b"
            r"|\b(video|youtube|yt)\b.+\b(shrink|small|smaller|pop\s*out|mini)\b",
            text,
        )
    ):
        return browser.miniplayer(), True

    # Window minimize only when clearly the window/browser (or bare "minimize").
    if re.search(r"minimi[sz]e", text):
        return actions.window("minimize"), True

    # FULLSCREEN (video/player) is NOT the same as MAXIMIZE (window).
    # "fullscreen the youtube video" -> press YouTube's 'f', never Win+Up.
    if re.search(
        r"\b(full\s*screen|fullscreen)\b"
        r"|\bmake (it |the )?(video |youtube )?(full\s*screen|fullscreen)\b"
        r"|\bgo full\s*screen\b"
        r"|\b(exit|leave|stop|end)\b.+\b(theater|cinema)\b"
        r"|\b(theater|cinema)\s*mode\b",
        text,
    ):
        # Theater/cinema mode (YouTube 't') — not the same as fullscreen, but
        # people often mean "make the video normal size again".
        if re.search(r"\b(theater|cinema)\b", text) and _BROWSER:
            if re.search(r"\b(exit|leave|stop|end|off|default)\b", text):
                return browser.player_key("t"), True
            return browser.player_key("t"), True
        if re.search(r"\b(exit|leave|stop|end)\b.*\b(full\s*screen|fullscreen)\b"
                     r"|\b(full\s*screen|fullscreen)\b.*\b(off|exit)\b"
                     r"|\bexit theater\b", text):
            if _BROWSER:
                return browser.fullscreen(exit_fs=True), True
            return actions.press_keys("escape"), True
        if _BROWSER:
            return browser.fullscreen(exit_fs=False), True
        # No controlled browser — still don't maximize; try F11 / f.
        if "youtube" in text or "video" in text:
            return actions.press_keys("f"), True
        return actions.press_keys("f11"), True

    # Maximize = grow the WINDOW only (never treat as video fullscreen).
    if re.search(r"\bmaximi[sz]e\b", text) and not re.search(r"\b(full\s*screen|fullscreen|video)\b", text):
        return actions.window("maximize"), True
    if re.search(r"switch (?:the )?(window|app)|alt tab|switch windows", text):
        return actions.window("switch"), True
    if re.search(r"show (?:me )?(?:the )?desktop$", text) or text in (
        "show desktop", "go to desktop",
    ):
        return actions.window("desktop"), True

    # ---- system -------------------------------------------------------
    if re.search(r"(take a |grab a )?screen ?shot", text):
        return actions.screenshot(), True
    if re.search(r"lock (?:the |my )?(computer|pc|laptop|screen)$", text) or text == "lock screen":
        return actions.lock_pc(), True

    # ---- hardware / system stats -------------------------------------
    # Do NOT match bare "charge" (e.g. "charge my phone") or small-talk.
    if re.search(r"\bbattery\b|power level|battery (percent|percentage|status)", text):
        return actions.battery_status(), True
    if re.search(r"\bcpu\b|processor (usage|load)", text):
        return actions.cpu_status(), True
    if re.search(r"\bram\b|memory (usage|status)|how much memory", text):
        return actions.ram_status(), True
    if re.search(r"system (report|status|stats|health)", text):
        return actions.system_report(), True

    # ---- memory ------------------------------------------------------
    m = re.match(r"remember(?: that)? my (.+?) (?:is|are) (.+)", text)
    if m:
        memory.remember(m.group(1), m.group(2))
        return f"Got it. I'll remember your {m.group(1)}.", True
    m = re.match(r"what(?:'s| is) my (.+)", text)
    if m:
        val = memory.recall(m.group(1))
        if val:
            return f"Your {m.group(1)} is {val}.", True

    if re.search(r"shut ?down|restart|reboot", text):
        return "Shutdown and restart are disabled for safety. Do it manually.", False

    # ---- small talk ----------------------------------------------------
    if re.search(r"what.?s the time|what time is it|tell me the time", text):
        return actions.current_time(), True
    if re.search(r"what.?s the date|what day is it|todays date", text):
        return actions.current_date(), True
    if re.fullmatch(r"(hello|hi|hey there|good (morning|afternoon|evening))", text):
        return "Hello. NEURON at your service.", True
    if re.search(r"how are you( doing)?\b", text):
        return "All systems nominal. Ready when you are.", True
    if re.search(r"who are you|your name", text):
        return "I am NEURON. Neural Engine for Unified Reasoning and Operational Navigation.", True
    if re.search(r"\b(thank you|thanks)\b", text):
        return "Anytime.", True

    # ---- speech engine identity (never let the LLM invent Windows SR) ----
    if re.search(
        r"(what|which).{0,40}(speech|voice|stt|whisper|recognition|ears|listening)"
        r"|(speech|voice) recognition.{0,20}(using|use|running)"
        r"|are you using (whisper|windows speech|browser speech)",
        text,
    ):
        return stt.get_engine().status_report(), True

    # ---- LLM reasoning fallback: handle ANYTHING else ----------------
    if brain_llm.is_enabled():
        # Prefer normalized intent; keep original words for the model.
        result = _run_with_llm(raw, normalized=text)
        if result is not None:
            return result

    # No matching intent and no LLM — stay silent, do nothing.
    return None, False


# Map action names the LLM can emit -> real functions in actions.py
# Web actions go through _web_open/_web_search so they land in the SAME
# controlled browser that play_result / click_text act on.
_EXECUTORS = {
    "open_app": lambda a: actions.open_app(a.get("name", "")),
    "steam_goto": lambda a: actions.steam_goto(a.get("section", "library")),
    "steam_select_account": lambda a: actions.steam_select_account(
        int(a.get("index", 1) or 1), a.get("name", "") or ""
    ),
    "learn_app": lambda a: app_learner.learn_app(a.get("name", "") or a.get("target", "") or "this"),
    "train_pc": lambda a: __import__("pc_trainer").start_training(
        deep_learn=bool(a.get("deep_learn", True))
    ),
    "training_status": lambda a: __import__("pc_trainer").status_report(),
    "stop_training": lambda a: __import__("pc_trainer").stop_training(),
    "open_website": lambda a: _web_open(a.get("site", ""), a.get("browser", "")),
    "search_site": lambda a: _web_search(a.get("site", ""), a.get("query", ""), a.get("browser", "")),
    "search_web": lambda a: actions.search_web(a.get("query", "")),
    "type_text": lambda a: actions.type_text(a.get("text", "")),
    "press_keys": lambda a: actions.press_keys(a.get("keys", "")),
    "click": lambda a: actions.click(a.get("button", "left"), bool(a.get("double", False))),
    "move_mouse": lambda a: actions.move_mouse(a.get("direction", ""), int(a.get("amount", 200))),
    "scroll": lambda a: actions.scroll(
        a.get("direction", "down"),
        app=a.get("app", "") or a.get("where", "") or "",
    ),
    "page_scroll": lambda a: (
        browser.page_scroll(a.get("direction", "down"), int(a.get("amount", 900)))
        if _BROWSER else actions.scroll(a.get("direction", "down"))
    ),
    "volume": lambda a: actions.volume(a.get("action", "up")),
    "media": lambda a: actions.media(a.get("action", "playpause")),
    "window": lambda a: actions.window(a.get("action", "")),
    "close_app": lambda a: actions.close_app(a.get("name", "") or a.get("app", "")),
    "screenshot": lambda a: actions.screenshot(all_monitors=bool(a.get("all") or a.get("all_monitors"))),
    "describe_screen": lambda a: (
        vision_agent.describe_screens(a.get("request", "") or a.get("goal", ""))
        if vision_agent and vision_agent.is_enabled()
        else "Vision isn't ready yet."
    ),
    "play_result": lambda a: (
        browser.youtube_home_play(int(a.get("index", 1)))
        if _BROWSER and str(a.get("where", "")).lower() in ("home", "homepage", "feed", "true", "1")
        else browser.play_result(int(a.get("index", 1)))
        if _BROWSER else "Browser control isn't available."
    ),
    "youtube_home": lambda a: (
        browser.youtube_home() if _BROWSER else "Browser control isn't available."
    ),
    "youtube_home_play": lambda a: (
        browser.youtube_home_play(int(a.get("index", 1)))
        if _BROWSER else "Browser control isn't available."
    ),
    "play_by_title": lambda a: (
        browser.play_by_title(a.get("title", "") or a.get("query", "") or a.get("name", ""))
        if _BROWSER else "Browser control isn't available."
    ),
    "skip_ad": lambda a: browser.skip_ad() if _BROWSER else "Browser control isn't available.",
    "fullscreen": lambda a: (
        browser.fullscreen(bool(a.get("exit") or a.get("exit_fs")))
        if _BROWSER else "Browser control isn't available."
    ),
    "miniplayer": lambda a: (
        browser.miniplayer() if _BROWSER else "Browser control isn't available."
    ),
    "player_key": lambda a: (
        browser.player_key(a.get("key", "m")) if _BROWSER else "Browser control isn't available."
    ),
    "ensure_playback": lambda a: (
        browser.ensure_playback(a.get("want", "play"))
        if _BROWSER else "Browser control isn't available."
    ),
    "click_text": lambda a: browser.click_text(a.get("text", "")) if _BROWSER else "Browser control isn't available.",
    "computer_use": lambda a: vision_agent.computer_use(a.get("goal", "")) if vision_agent and vision_agent.is_enabled() else "Vision control isn't ready yet.",
    "create_folder": lambda a: actions.create_folder(a.get("name", ""), a.get("location", "desktop")),
    "create_file": lambda a: actions.create_file(a.get("name", ""), a.get("content", ""), a.get("location", "desktop")),
    "open_folder": lambda a: actions.open_folder(a.get("location", "")),
    "run_shell": lambda a: actions.run_shell(a.get("command", "")),
    "wait": lambda a: actions.wait(a.get("seconds", 1)),
    "system_report": lambda a: actions.system_report(),
}


def _execute_plan(result):
    """Run a plan's steps. Returns (outcomes, errors, unknown, failed_step)."""
    steps = result.get("steps", []) or []
    outcomes, errors, unknown = [], [], []
    failed_step = None
    for step in steps:
        name = (step.get("action") or "").strip()
        fn = _EXECUTORS.get(name)
        if not fn:
            if name:
                unknown.append(name)
            continue
        try:
            out = fn(step.get("args", {}) or {})
            if isinstance(out, str) and out.strip():
                outcomes.append(out.strip())
        except Exception as exc:
            errors.append(str(exc))
            failed_step = step
            break  # a failed step makes the rest of the plan meaningless
    return outcomes, errors, unknown, failed_step


def _run_with_llm(raw: str, normalized: str = ""):
    """Ask the reasoning core for a plan, execute it, and self-correct once
    if a step fails — like a human noticing and retrying differently."""
    intent = (normalized or "").strip() or nlu.best_text(raw)
    context = memory.context_blob(intent or raw)
    # Mode 1B: attach live multi-monitor glance so the planner knows what's on screen.
    screen_ctx = _LAST_SCREEN_CTX or _refresh_screen_glance(intent or raw)
    if screen_ctx:
        blob = screen_ctx
        if len(blob) > 2200:
            blob = blob[:2200] + "\n…"
        context = (context + "\n\nLIVE SCREENS (trust this over guessing):\n" + blob).strip()
    result = brain_llm.plan(raw, context, normalized=intent)
    if result is None:
        return None

    steps = result.get("steps", []) or []
    outcomes, errors, unknown, failed_step = _execute_plan(result)

    # Self-correction: report the exact failure back to the model, once.
    if errors and failed_step is not None:
        fix_context = (
            context
            + "\n\nIMPORTANT: your previous plan for this exact request just ran and FAILED."
            + f"\nFailed action: {json.dumps(failed_step)}"
            + f"\nError: {errors[-1]}"
            + "\nGive corrected steps that avoid this error (different action or args)."
            + " If it truly cannot be done, return empty steps and explain in say."
        )
        retry = brain_llm.plan(raw, fix_context, normalized=intent)
        if retry is not None and (retry.get("steps") or []):
            r_outcomes, r_errors, r_unknown, _ = _execute_plan(retry)
            if not r_errors and r_outcomes:
                steps = retry.get("steps") or steps
                outcomes, errors, unknown = r_outcomes, [], r_unknown
                result = retry

    say = (result.get("say") or "").strip()

    # Honesty: if a step actually failed, say so instead of faking success.
    if errors:
        say = "I hit a problem: " + "; ".join(errors)
    elif unknown and not outcomes:
        say = f"I didn't know how to run: {', '.join(unknown)}."
    elif outcomes:
        # Prefer reporting what actually happened over the model's guess.
        say = outcomes[-1]
    elif not steps:
        # Pure conversation — keep the model's spoken reply.
        pass
    else:
        # Steps were listed but none produced a result — don't fake success.
        say = say or "I planned it, but nothing actually ran."

    memory.log("user", raw)
    if say:
        memory.log("neuron", say)
    return (say or None, bool(steps or say))
