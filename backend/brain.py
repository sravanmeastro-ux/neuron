"""N.E.U.R.O.N brain — turns spoken sentences into actions.

handle_command(text) -> (reply: str | None, acted: bool)
Returns reply=None when the sentence doesn't match any command
(so random conversation doesn't trigger anything).
"""

import json
import re
from pathlib import Path

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


def _agent_config() -> dict:
    """Phase 1 agent settings from config.json (overridable in tests)."""
    try:
        return (
            json.loads(Path(__file__).resolve().parent.joinpath("config.json").read_text(encoding="utf-8")).get("agent")
            or {}
        )
    except Exception:
        return {}


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
    """NEURON command entry.

    Phase 1 brain (default): context → intent → planner → tools → executor →
    verifier → replan. Escape hatches only for confirm / wake / stop / monitor focus.
    Legacy regex routes remain as fallback when the agent cannot plan (Ollama down).
    """
    # NLU: turn casual / messy speech into a short simple intent first.
    _nlu = nlu.understand(raw)
    text = _nlu["canonical"] or _nlu["cleaned"]
    if _nlu.get("rewrote"):
        print(f"[nlu] '{_nlu['cleaned']}' -> '{text}'", flush=True)
    if not text:
        return None, False

    agent_attempted = False

    # ---- confirm pending high-risk / confirm-tier tool ---------------
    if re.fullmatch(r"(?:please )?(?:confirm|yes|do it|proceed|go ahead)(?: please)?", text):
        try:
            from neuron.safety import confirm as confirm_mod
            from neuron.brain import executor
            pending = confirm_mod.take_pending()
            if pending:
                plan = {
                    "say": "",
                    "steps": [{
                        "action": pending["action"],
                        "args": dict(pending.get("args") or {}),
                    }],
                }
                plan["steps"][0]["args"]["confirmed"] = True
                er = executor.execute_plan(plan, confirmed=True)
                if er.errors:
                    return "I hit a problem: " + "; ".join(er.errors), True
                return (er.outcomes[-1] if er.outcomes else "Done."), True
            return "Nothing waiting for confirmation.", True
        except Exception as exc:
            return f"Confirm failed: {exc}", True
    if re.fullmatch(r"(?:please )?(?:cancel|abort|never ?mind|no)(?: please)?", text):
        try:
            from neuron.safety import confirm as confirm_mod
            if confirm_mod.take_pending():
                return "Cancelled.", True
        except Exception:
            pass
    # Safety status
    if re.search(r"\b(safety|permission) (status|tiers|levels)\b|\bwhat (can|will) you (do|run)\b", text):
        try:
            from neuron.safety.levels import tier_prompt
            return tier_prompt(), True
        except Exception:
            pass

    # ---- hands-free / wake word preferences --------------------------
    if re.search(
        r"\b(hands[\s-]?free(?: mode)?|don'?t (?:require|need) (?:my |a )?name|"
        r"no wake(?: word)?|you don'?t need (?:me to say )?(?:neuron|your name)|"
        r"stop (?:making me )?say (?:neuron|your name)|just listen|"
        r"you have (?:full )?access(?: to (?:my )?(?:pc|computer|laptop))?)\b",
        text,
    ) and not re.search(r"\b(require|need|enable|turn on)\b.+\b(wake|name|neuron)\b", text):
        import voice_mode
        memory.remember(
            "pc access",
            "full desktop control granted; act on plain speech without waiting to be named",
        )
        return voice_mode.set_wake_word_required(False), True
    if re.search(
        r"\b(require (?:a )?wake(?: word)?|wake word on|"
        r"only (?:listen|respond|act) (?:when|if) I say (?:your name|neuron)|"
        r"make me say (?:neuron|your name))\b",
        text,
    ):
        import voice_mode
        return voice_mode.set_wake_word_required(True), True

    # ---- conversation mode (Phase 6) ---------------------------------
    if re.search(
        r"\b(conversation mode|chat mode|keep listening|stay listening|"
        r"don'?t (?:make me )?say (?:neuron|your name) (?:each|every|again))\b",
        text,
    ) and not re.search(r"\b(end|stop|exit|leave)\b.+\bconversation\b", text):
        import voice_mode
        return voice_mode.set_conversation_mode(True), True
    if re.search(
        r"\b(end conversation|stop conversation|exit conversation|"
        r"leave conversation mode|conversation mode off)\b",
        text,
    ):
        import voice_mode
        return voice_mode.set_conversation_mode(False), True

    # ---- stop / interrupt (TTS + AgentLoop barge-in) -----------------
    try:
        from neuron.speech.interrupt import is_stop_phrase
        if is_stop_phrase(text):
            return "__STOP_SPEECH__", True
    except Exception:
        if re.search(
            r"\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron|"
            r"(?:hey\s+)?neuron[,.]?\s+stop)\b|^(?:please\s+)?stop[.!]?$",
            text,
            re.I,
        ):
            return "__STOP_SPEECH__", True

    # ---- monitor focus: look at / use screen|monitor N / left|right|main ----
    m_focus = re.search(
        r"\b(?:look at|see|watch|use|focus on|listen to|work on)\s+"
        r"(?:my\s+|the\s+)?"
        r"(?:"
        r"(?:left|right|main|other|primary|secondary)\s+(?:screen|monitor|display)"
        r"|(?:screen|monitor|display)\s*(?:number\s*)?(one|two|three|four|five|first|second|third|\d{1,2})"
        r")"
        r"\b"
        r"|\b(?:screen|monitor|display)\s*(?:number\s*)?(one|two|three|four|five|first|second|third|\d{1,2})\b",
        text,
    )
    if m_focus:
        import monitor_focus
        from neuron.windows import monitors as mon_mod
        phrase = m_focus.group(0)
        mon = mon_mod.resolve_monitor_ref(phrase)
        if not mon:
            # Legacy fallback one/two
            word = (m_focus.group(1) or m_focus.group(2) or "1").lower()
            mid = 1 if word in ("1", "one", "first") else 2
        else:
            mid = int(mon["id"])
        monitor_focus.set_focus(mid)
        if vision_agent and vision_agent.is_enabled():
            desc = vision_agent.describe_screens(
                f"monitor {mid} only", monitor_id=mid
            )
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

    # ---- Phase 9: learn PROCEDURE by demonstration (before AgentLoop) --
    # Must win over recipe match for "learn how I create a Blender project".
    try:
        from neuron.learning import teach as teach_mod
        from neuron.learning import procedures as proc_mod

        goal = teach_mod.parse_learn_goal(text)
        if goal is not None:
            return teach_mod.start(goal), True

        if teach_mod.is_teaching() and re.search(
            r"\b(done|finished|that'?s it|stop learning|save (?:the )?(?:procedure|skill|workflow)|"
            r"end (?:the )?lesson|i'?m done)\b",
            text,
        ):
            m_as = re.search(r"\b(?:as|named|called)\s+(.+)$", text)
            return teach_mod.finish(m_as.group(1).strip() if m_as else ""), True

        if teach_mod.is_teaching() and re.fullmatch(
            r"(?:please )?(?:cancel|abort)(?: teaching| learning| this)?",
            text,
        ):
            return teach_mod.cancel(), True

        if re.search(
            r"\b(list|show) (?:my )?(?:learned )?(?:procedures?|skills?|workflows?)\b"
            r"|\bwhat (?:procedures?|skills?) (?:do you|have you) (?:know|learned)\b",
            text,
        ):
            return proc_mod.list_summary(), True

        if re.search(r"\b(teaching status|am i teaching|learning status)\b", text):
            return teach_mod.status(), True

        m_forget = re.match(
            r"(?:forget|delete|unlearn)\s+(?:the\s+)?(?:skill|procedure|workflow)\s+(.+)$",
            text,
        )
        if m_forget:
            return proc_mod.delete_procedure(m_forget.group(1).strip()), True
    except Exception as exc:
        print(f"[learn] early procedure path skipped: {exc}", flush=True)

    # ---- AgentLoop closed-loop brain (OPAVR) -------------------------
    _acfg = _agent_config()
    if _acfg.get("enabled", True) and _acfg.get("agent_first", True):
        try:
            from neuron.brain import agent as neuron_agent
            say, acted, meta = neuron_agent.run(
                raw,
                use_rules_fallback=bool(_acfg.get("legacy_fallback", True)),
                screen_ctx=_LAST_SCREEN_CTX or "",
            )
            agent_attempted = True
            if meta.get("path") == "rules_fallback" or (say is None and not acted):
                print("[agent] planner unavailable -> legacy rules", flush=True)
            else:
                goal = meta.get("goal") or {}
                print(
                    f"[agent] AgentLoop path={meta.get('path')} "
                    f"status={goal.get('status')} "
                    f"steps={len(meta.get('steps') or [])} "
                    f"recovered={meta.get('recovered')} "
                    f"replanned={meta.get('replanned')} "
                    f"ms={meta.get('elapsed_ms')}",
                    flush=True,
                )
                return (say or None), acted
        except Exception as exc:
            print(f"[agent] AgentLoop error -> legacy: {exc}", flush=True)

    # ---- multi-screen / any-app vision Q&A ---------------------------
    # YouTube tile count uses DOM (precise). Everything else uses active-app vision.
    if vision_agent and vision_agent.is_enabled() and (
        re.search(
            r"\bwhat(?:'s| is|s) on (?:my |the )?(?:screen|screens|monitor|monitors|display|displays)\b"
            r"|\bdescribe (?:my |the )?(?:screen|screens|monitor|monitors|desktop|display|window|app)s?\b"
            r"|\blook at (?:my |the )?(?:screen|screens|monitor|monitors)\b"
            r"|\bcan you see (?:my |the )?(?:screen|screens|desktop)\b"
            r"|\b(how many|what|which|list|count)\b.+\b(on (?:my |the )?screen|can you see|do you see)\b"
            r"|\b(can you|do you) see\b.+\b(on|in|there)\b"
            r"|\bwhat(?:'s| is) (?:that|this)\b",
            text,
        )
        or (hasattr(vision_agent, "_SCREEN_QA") and vision_agent._SCREEN_QA.search(text))
    ):
        # Precise YouTube feed listing when controlled browser is on YouTube.
        yt_video_q = bool(re.search(r"\bvideos?\b", text)) and not re.search(
            r"\b(play|open|click|select|start)\b", text
        )
        if _BROWSER and yt_video_q:
            try:
                if browser.on_youtube():
                    return browser.list_visible_videos(), True
            except Exception:
                pass
        return vision_agent.answer_screen(text), True

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
        # "learn my computer" / deep / thoroughly → full inventory + deep UI on priority apps
        deep = bool(re.search(
            r"\b(deep|thorough|fully|deep.?learn|every|all|whole|entire|perfect|"
            r"complete|learn (?:every|all|my) (?:app|computer|pc|os|system))\b",
            text,
        )) and not re.search(r"\b(quick|fast|inventory only)\b", text)
        # Default for plain "learn my computer" is now FULL (user expectation).
        if re.search(r"\b(computer|pc|laptop|system|machine|os)\b", text):
            deep = not re.search(r"\b(quick|fast|inventory only)\b", text)
        return pc_trainer.start_training(deep_learn=deep, deep_limit=40, force_refresh=deep), True

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

    # Priority playbooks: Discord, YouTube, Google, Opera, Settings, Steam, Blender, Notepad, WhatsApp
    if re.search(
        r"\btrain (?:the )?(?:priority|main|important) apps\b"
        r"|\btrain (?:neuron )?(?:on )?(?:discord|youtube|google|opera|steam|blender|notepad|whatsapp)\b"
        r"|\blearn (?:how to use )?(?:discord|youtube|google|opera|windows settings|steam|blender|notepad|whatsapp)"
        r"(?: and|,| )+(?:discord|youtube|google|opera|settings|steam|blender|notepad|whatsapp)\b"
        r"|\bteach (?:yourself|neuron) (?:these|those|priority) apps\b",
        text,
    ):
        import priority_apps
        # Live UI scan can open windows — user explicitly asked to train.
        return priority_apps.train_live(), True

    # Learn workflows from Google / YouTube tutorials (not only mouse recording)
    if re.search(
        r"\b(ask google|from youtube|from google|learn from|train from|"
        r"watch(?: a)?(?: youtube)?(?: video)?|search (?:google|youtube) for how)\b",
        text,
    ) or (
        re.search(r"\b(learn|train|teach)\b.+\bhow to\b", text)
        and re.search(r"\b(youtube|google|tutorial|internet|online|web)\b", text)
    ):
        import howto_learn
        reply = howto_learn.learn_from_utterance(text)
        if reply:
            return reply, True

    # Stop / disable the old "learn every focused window" spam.
    if re.search(
        r"\b(stop|disable|turn off|don'?t)\b.+\b(auto\s*learn|learning every|watching (apps|windows))\b"
        r"|\bstop (watching|scanning) (apps|windows|every app)\b",
        text,
    ):
        try:
            import json as _json
            from pathlib import Path as _P
            path = _P(__file__).resolve().parent / "config.json"
            cfg = _json.loads(path.read_text(encoding="utf-8"))
            al = cfg.setdefault("auto_learn", {})
            al["watch_foreground"] = False
            al["learn_on_open"] = False
            path.write_text(_json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        return (
            "Okay — I won't scan apps as you open them. "
            "Say 'learn my computer' to map installed apps, or 'learn how X works' for one app."
        ), True

    # ---- Windows Settings (ms-settings URIs) -------------------------
    if (
        re.search(
            r"\bwindows settings\b"
            r"|\b(bluetooth|wi-?fi|display|sound|personalization|windows update|"
            r"notifications)\s+settings?\b"
            r"|\bopen (?:the )?(?:settings|setting)\b"
            r"|\bgo to (?:the )?settings\b",
            text,
        )
        and not re.search(
            r"\b(steam|blender|discord|chrome|opera|whatsapp|youtube|spotify)\b",
            text,
        )
    ):
        page = "home"
        for name in (
            "bluetooth", "wifi", "wi-fi", "display", "sound", "notifications",
            "personalization", "network", "apps", "privacy", "accounts",
            "update", "storage", "gaming", "system",
        ):
            if re.search(rf"\b{re.escape(name)}\b", text):
                page = "wifi" if name == "wi-fi" else name
                break
        if re.search(r"\bwindows update\b", text):
            page = "update"
        return actions.open_settings(page), True

    # ---- Phase 9: reuse learned procedure by phrase (fallback path) ---
    try:
        from neuron.learning import procedures as proc_mod
        from neuron.learning import teach as teach_mod
        if not teach_mod.is_teaching() and not re.search(
            r"\b(learn|teach|record|watch me)\b", text
        ):
            hit = proc_mod.match(text)
            if hit:
                return proc_mod.run_procedure(proc_id=hit.get("id") or "", query=text), True
    except Exception as exc:
        print(f"[learn] procedure reuse skipped: {exc}", flush=True)

    # ---- click workflow recorder (optional; NEVER always-on) ---------
    import click_recorder
    if re.search(
        r"\b(start|begin)\b.+\b(recording?|record)\b.+\b(clicks?|mouse|workflow|this)\b"
        r"|\b(start|begin) recording(?: clicks?| my clicks?| this)?\b"
        r"|\brecord (?:my )?(?:clicks?|this workflow|a workflow)\b"
        r"|\bwatch (?:my|these) clicks?\b",
        text,
    ):
        return click_recorder.start(), True
    if re.search(
        r"\b(stop|finish|end|save) recording\b"
        r"|\bsave (?:the |this )?(?:recording|clicks?|workflow)\b",
        text,
    ):
        # Optional name: "stop recording as open friends"
        m_name = re.search(
            r"(?:as|named|called)\s+(.+)$",
            text,
        )
        name = m_name.group(1).strip() if m_name else ""
        return click_recorder.stop(name), True
    if re.fullmatch(r"(?:cancel|abort) recording", text):
        return click_recorder.cancel(), True
    if re.search(r"\b(list|show) (?:my )?(?:click|mouse) (?:recipes?|recordings?|workflows?)\b", text):
        return click_recorder.list_recipes(), True
    if re.search(r"\b(recording status|am i recording|click recorder status)\b", text):
        return click_recorder.status(), True
    if re.search(
        r"\b(replay|play back|playback)\b.+\b(clicks?|recording|recipe|workflow)\b"
        r"|\b(replay|play back)\s+(?:my\s+)?(?:saved\s+)?(?:clicks?|recording|recipe|workflow)\b"
        r"|\breplay\s+[\w][\w\s\-]{1,40}$",
        text,
    ) and not re.search(r"\b(video|youtube|yt|song|track|music)\b", text):
        m = re.search(
            r"\b(?:replay|play back)\s+(?:the\s+)?(?:recording|recipe|workflow|clicks?)?\s*(.*)$",
            text,
        )
        q = (m.group(1).strip() if m else "") or text
        q = re.sub(r"^(?:the\s+)?(?:recording|recipe|workflow|clicks?)\s*", "", q).strip()
        return click_recorder.replay(query=q or text), True

    # If user says "remember that as X" while/after recording, save clicks under that name.
    if click_recorder.is_recording() and re.match(
        r"(?:remember (?:that|this) as|save that as|call that|when i say)\s+(.+)$",
        text,
    ):
        phrase = re.match(
            r"(?:remember (?:that|this) as|save that as|call that|when i say)\s+(.+)$",
            text,
        ).group(1).strip()
        phrase = re.sub(r"\s*(?:do that|and do that|please)$", "", phrase).strip()
        return click_recorder.stop(phrase), True

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

    # ---- teach / remember voice recipes ------------------------------
    # Only alias teaching — NEVER steal "remember that my favorite color is red".
    import voice_recipes
    m_rem = re.match(
        r"(?:remember (?:that|this) as|save that as|call that|when i say)\s+(.+)$",
        text,
    )
    if m_rem:
        phrase = m_rem.group(1).strip()
        phrase = re.sub(r"\s*(?:do that|and do that|please)$", "", phrase).strip()
        if phrase:
            return voice_recipes.remember_last_as(phrase), True
    if re.fullmatch(
        r"(?:please )?(?:remember that|save that|learn that command|remember this command)"
        r"(?: please)?",
        text,
    ):
        last = voice_recipes.last_success()
        if last.get("phrase") and last.get("action"):
            return voice_recipes.remember(
                last["phrase"], last["action"], last.get("args") or {}
            ), True
        return (
            "Do the action once, then say 'remember that as open friends chat' "
            "(or whatever phrase you want)."
        ), True

    # Known voice recipes (friends chat, discord, taught phrases, …)
    recipe = voice_recipes.match(text)
    if recipe:
        action = recipe.get("action") or ""
        args = recipe.get("args") or {}
        try:
            if action == "discord_friends":
                msg = actions.discord_friends()
            elif action == "youtube_home":
                msg = browser.youtube_home() if _BROWSER else "Browser control isn't available."
            elif action == "open_settings":
                msg = actions.open_settings(args.get("page", "home") or "home")
            elif action == "replay_clicks":
                msg = click_recorder.replay(
                    recipe_id=args.get("id", "") or "",
                    query=args.get("say", "") or text,
                )
            elif action == "steam_goto":
                msg = actions.steam_goto(args.get("section", "friends"))
            elif action == "open_app":
                msg = actions.open_app(args.get("name", "") or recipe.get("app", ""))
            elif action == "open_website":
                msg = _web_open(args.get("site", ""), args.get("browser", ""))
            elif action == "search_site":
                msg = _web_search(
                    args.get("site", ""), args.get("query", ""), args.get("browser", "")
                )
            elif action == "computer_use" and vision_agent and vision_agent.is_enabled():
                msg = vision_agent.computer_use(args.get("goal") or text)
            elif action in _EXECUTORS:
                msg = _EXECUTORS[action](args)
            else:
                msg = None
            if msg is not None:
                voice_recipes.note_success(text, action, args, say=str(msg))
                voice_recipes.auto_save_if_useful(text, action, args)
                return str(msg), True
        except Exception as exc:
            # Fall through to Steam / open / vision rather than hard-fail
            print(f"[voice_recipes] {action} failed: {exc}", flush=True)

    # Bare "open friends chat" / "friends chat" without recipe hit
    if re.search(
        r"\b(open |go to |show )?(the )?(friends?(?: and)? chat|friend chat|dms|direct messages)\b",
        text,
    ) and not re.search(r"\bsteam\b", text):
        try:
            msg = actions.discord_friends()
            voice_recipes.note_success(text, "discord_friends", {})
            voice_recipes.auto_save_if_useful("open friends chat", "discord_friends", {})
            return msg, True
        except Exception as exc:
            if vision_agent and vision_agent.is_enabled():
                return vision_agent.computer_use(
                    "Open Discord Friends / DMs chat list"
                ), True
            return f"Couldn't open Friends chat: {exc}", True

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

    # ---- list / count videos on screen (NOT play) -------------------
    # "how many videos can you see" must never become play_result.
    if _BROWSER and re.search(
        r"\b(how many|count|list|what|which|name)\b.+\bvideos?\b"
        r"|\bvideos?\b.+\b(can you see|do you see|on (?:my |the )?screen|visible|right now)\b"
        r"|\b(see|saw|seeing)\b.+\bvideos?\b.+\b(screen|youtube|there)\b",
        text,
    ) and not re.search(r"\b(play|open|click|select|start)\b", text):
        try:
            import app_context
            app_context.set_app("youtube")
        except Exception:
            pass
        return browser.list_visible_videos(), True

    # ---- act inside the page: "play the 2nd video / result" ----------
    # Default = Nth video CURRENTLY VISIBLE on screen (after scroll counts).
    # Only force homepage navigation when they explicitly say homepage/home feed
    # AND are not pointing at the screen ("on screen", "i can see").
    _on_screen = bool(re.search(
        r"\b(?:on\s+(?:my\s+|the\s+)?screen|i\s+can\s+see|that\s+i\s+see|"
        r"visible|showing|in\s+(?:my\s+|the\s+)?view)\b",
        text,
    ))
    # Questions about videos are never play commands.
    _ask_about_videos = bool(re.search(
        r"\b(how many|what|which|list|count|tell me)\b",
        text,
    ))
    m = None
    if not _ask_about_videos:
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
    # Do NOT fire this for skip-ad / "not this video" / complaints / questions.
    if (
        _BROWSER
        and not _ask_about_videos
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
            if not agent_attempted and brain_llm.is_enabled():
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

    # ---- memory scopes (working / session / persistent) --------------
    m = re.match(r"remember(?: that)? my (.+?) (?:is|are) (.+)", text)
    if m:
        msg = memory.remember(m.group(1), m.group(2))
        if msg.lower().startswith("remembered") or "remembered" in msg.lower():
            return f"Got it. I'll remember your {m.group(1)}.", True
        return msg, True
    m = re.match(r"what(?:'s| is) my (.+)", text)
    if m:
        val = memory.recall(m.group(1))
        if val:
            return f"Your {m.group(1)} is {val}.", True
    m = re.match(r"forget(?: that)? my (.+)", text)
    if m:
        return memory.forget(m.group(1)), True
    if re.search(r"\b(clear|reset) working memory\b", text):
        try:
            from neuron.memory import scopes
            return scopes.clear_working(), True
        except Exception as exc:
            return str(exc), True
    if re.search(r"\b(clear|reset) session memory\b", text):
        try:
            from neuron.memory import scopes
            return scopes.clear_session(), True
        except Exception as exc:
            return str(exc), True
    if re.search(
        r"\b(forget everything permanently|clear (all )?persistent memory|"
        r"wipe (all )?persistent (facts|memory))\b",
        text,
    ):
        try:
            from neuron.memory import scopes
            return scopes.clear_persistent(confirm=True), True
        except Exception as exc:
            return str(exc), True
    if re.search(r"\b(clear|reset) (all )?memory\b", text):
        try:
            from neuron.memory import scopes
            return scopes.clear_all(confirm_persistent=False), True
        except Exception as exc:
            return str(exc), True
    if re.search(r"\b(what do you remember|memory status|list (my )?facts)\b", text):
        try:
            from neuron.memory import scopes
            st = scopes.status()
            facts = scopes.persistent().list_facts(8)
            bits = [
                f"Working: goal={st['working'].get('goal') or '(idle)'} "
                f"({st['working'].get('actions', 0)} actions)",
                f"Session: {st['session'].get('chat_turns', 0)} turns, "
                f"apps={', '.join(st['session'].get('apps') or []) or 'none'}",
                f"Persistent: {st['persistent'].get('facts', 0)} facts",
            ]
            if facts:
                bits.append("Facts: " + "; ".join(f"{k}={v}" for k, v in list(facts.items())[:5]))
            return " | ".join(bits), True
        except Exception as exc:
            return str(exc), True

    if re.search(r"shut ?down|restart|reboot", text):
        try:
            from neuron.safety.failsafe import power_actions_disabled_message
            return power_actions_disabled_message(), False
        except Exception:
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
    # Skip if Phase 1 agent already tried (avoids a second Ollama round-trip).
    if not agent_attempted and brain_llm.is_enabled():
        result = _run_with_llm(raw, normalized=text)
        if result is not None:
            return result

    # No matching intent and no LLM — stay silent, do nothing.
    return None, False


# Map action names the LLM can emit -> real functions in actions.py
# Web actions go through _web_open/_web_search so they land in the SAME
# controlled browser that play_result / click_text act on.
_EXECUTORS = {
    "open_app": lambda a: actions.open_app(
        (a.get("name") or a.get("application") or a.get("app") or "")
    ),
    "steam_goto": lambda a: actions.steam_goto(a.get("section", "library")),
    "discord_friends": lambda a: actions.discord_friends(),
    "open_settings": lambda a: actions.open_settings(a.get("page", "home") or "home"),
    "replay_clicks": lambda a: __import__("click_recorder").replay(
        recipe_id=a.get("id", "") or "",
        query=a.get("say", "") or a.get("name", "") or "",
    ),
    "steam_select_account": lambda a: actions.steam_select_account(
        int(a.get("index", 1) or 1), a.get("name", "") or ""
    ),
    "learn_app": lambda a: app_learner.learn_app(a.get("name", "") or a.get("target", "") or "this"),
    "train_pc": lambda a: __import__("pc_trainer").start_training(
        deep_learn=bool(a.get("deep_learn", True)),
        deep_limit=int(a.get("deep_limit", 40) or 40),
        force_refresh=bool(a.get("force_refresh", False) or a.get("force", False)),
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
        vision_agent.answer_screen(a.get("request", "") or a.get("goal", ""))
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
    "list_visible_videos": lambda a: (
        browser.list_visible_videos() if _BROWSER else "Browser control isn't available."
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
    "run_shell": lambda a: _safe_run_shell(a),
    "wait": lambda a: actions.wait(a.get("seconds", 1)),
    "system_report": lambda a: actions.system_report(),
}


def _safe_run_shell(a: dict) -> str:
    """Gate legacy run_shell through safety policy."""
    cmd = a.get("command", "")
    try:
        from neuron.safety import policy
        ok, reason = policy.allow("run_shell", {"command": cmd}, confirmed=bool(a.get("confirmed")))
        if not ok:
            from neuron.safety import confirm as confirm_mod
            confirm_mod.request_confirm("run_shell", {"command": cmd}, reason)
            return reason
    except Exception:
        return "Shell blocked (safety module unavailable)."
    return actions.run_shell(cmd)


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
    """Plan via Ollama; execute through neuron tool registry + verify/replan."""
    intent = (normalized or "").strip() or nlu.best_text(raw)
    screen_ctx = _LAST_SCREEN_CTX or _refresh_screen_glance(intent or raw)
    memory.log("user", raw)
    try:
        from neuron.brain import agent as neuron_agent
        from neuron.brain import tool_registry
        tool_registry.ensure_bootstrapped()
        say, acted = neuron_agent.run_legacy_llm(
            raw, normalized=intent, screen_ctx=screen_ctx or ""
        )
        if say is not None:
            if say:
                memory.log("neuron", say)
            return (say or None, acted)
    except Exception as exc:
        print(f"[agent] fallback to legacy executor: {exc}", flush=True)

    context = memory.context_blob(intent or raw)
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
    if errors and failed_step is not None:
        fix_context = (
            context
            + "\n\nIMPORTANT: your previous plan for this exact request just ran and FAILED."
            + f"\nFailed action: {json.dumps(failed_step)}"
            + f"\nError: {errors[-1]}"
            + "\nGive corrected steps that avoid this error (different action or args)."
        )
        retry = brain_llm.plan(raw, fix_context, normalized=intent)
        if retry is not None and (retry.get("steps") or []):
            r_outcomes, r_errors, r_unknown, _ = _execute_plan(retry)
            if not r_errors and r_outcomes:
                steps = retry.get("steps") or steps
                outcomes, errors, unknown = r_outcomes, [], r_unknown
                result = retry

    say = (result.get("say") or "").strip()
    if errors:
        say = "I hit a problem: " + "; ".join(errors)
    elif unknown and not outcomes:
        say = f"I didn't know how to run: {', '.join(unknown)}."
    elif outcomes:
        say = outcomes[-1]
    elif not steps:
        pass
    else:
        say = say or "I planned it, but nothing actually ran."

    if say:
        memory.log("neuron", say)
    return (say or None, bool(steps or say))
