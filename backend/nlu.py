"""Natural language understanding for N.E.U.R.O.N.

Design goal (user preference): speak NORMALLY —
  "open chrome", "close chrome", "pause the video"
— and have it work. Not fancy slang ("pull up", "fire up", "kill").

What this layer does:
  1) Strip polite fillers ("please", "can you", "hey neuron")
  2) Fix common speech-to-text mishears ("crome" → chrome)
  3) Normalize tiny grammar ("open the chrome" → "open chrome")
  4) Only rewrite phrases that are known confusion traps
     (e.g. minimize VIDEO ≠ minimize WINDOW)
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Speech / STT cleanup
# ---------------------------------------------------------------------------

MISHEARS = [
    (r"\byou ?tube\b", "youtube"),
    (r"\bu ?tube\b", "youtube"),
    (r"\byoutube\.com\b", "youtube"),
    (r"\b(crome|chrom|krome)\b", "chrome"),
    (r"\bgoogle chrome\b", "chrome"),
    (r"\bnote ?pad\b", "notepad"),
    (r"\bhome ?page\b", "homepage"),
    (r"\bscreen ?shot\b", "screenshot"),
    (r"\bwhats ?app\b|\bwhat sapp\b", "whatsapp"),
    (r"\bskip (the |this |that )?(sad|add|adds|at|hat)\b", r"skip \1ad"),
    (r"\b(video|videos) in youtube\b", r"\1 on youtube"),
    (r"\bfull ?screen\b", "fullscreen"),
    (r"\bmini ?player\b", "miniplayer"),
    (r"\bdis ?cord\b", "discord"),
    (r"\bspot ?ify\b", "spotify"),
    (r"\bgit ?hub\b", "github"),
    (r"\bnet ?flix\b", "netflix"),
]

# Polite fluff only — does not invent slang commands.
# Do NOT strip "jarvis"/"neuron" mid-phrase (video titles like "Coding Jarvis").
FILLERS = (
    r"\b(?:please|pls|plz|kindly)\b",
    r"\b(?:um+|uh+|ah+|erm+|hmm+)\b",
    r"\b(?:can you|could you|would you|will you|"
    r"i want you to|i need you to|i would like you to|i\'?d like you to|"
    r"go ahead and|help me)\b",
    r"\b(?:for me|right now)\b",
)

# Vocative only: "hey neuron,", "jarvis play…", "neuron:" — not mid-title words.
ASSISTANT_LEAD = (
    r"^(?:hey |hi |hello )?(?:neuron|jarvis|assistant)\s*[,:]?\s+",
    r"\b(?:neuron|jarvis|assistant)\s*[,:]\s+",
)

LEAD_INS = (
    r"^(?:okay|ok|alright|all right|so|hey|hi|hello)\s+",
    r"^(?:i (?:want|need|would like|d like) (?:you |for you )?to)\s+",
    r"^(?:i want you|would you|will you|can you|could you)\s+",
    r"^(?:go ahead and|now|just)\s+",
)

# ---------------------------------------------------------------------------
# Normal-speech polish (NOT slang dictionaries)
# ---------------------------------------------------------------------------

# "open the chrome" / "close my notepad" / "open a youtube"
_ARTICLE = r"(?:the|my|a|an)\s+"

NORMALIZERS: list[tuple[str, str]] = [
    # open/close + article → plain open/close
    (rf"^(open|close|quit|exit)\s+{_ARTICLE}(.+)$", r"\1 \2"),
    # "open up chrome" → open chrome (tiny grammar, still normal)
    (r"^(open|close)\s+up\s+(.+)$", r"\1 \2"),
    # "start chrome" / "launch chrome" → open chrome (common normal verbs)
    # Do NOT rewrite "start recording …" / "start watching …"
    (r"^(start|launch)\s+(?!recording\b|watching\b|listen(?:ing)?\b)(.+)$", r"open \2"),
    # "quit/exit chrome" already handled by close rule; normalize to close
    (r"^(quit|exit)\s+(?!fullscreen\b)(.+)$", r"close \2"),
    # Gerund speech: "playing the second video…" → play …
    (r"^playing\b", "play"),
    (r"^watching\b", "watch"),
    (r"^opening\b", "open"),
    (r"^scrolling\b", "scroll"),
]

# Only confusion traps that caused real bugs — keep short.
CONFUSION_FIXES: list[tuple[str, str]] = [
    # analyze/study → learn (so app learning always fires)
    (r"^(?:analy[sz]e|inspect|figure out|understand)\s+(?:how\s+)?"
     r"(.+?)\s+works$",
     r"learn how \1 works"),
    (r"^(?:analy[sz]e|inspect)\s+(?:the\s+)?(.+?)(?:\s+app)?$",
     r"learn how \1 works"),
    # video miniplayer ≠ browser minimize
    (r"^minimi[sz]e\s+(?:the\s+)?(?:video|youtube|yt|player)$", "minimize the video"),
    (r"^minimi[sz]e\s+(?:the\s+)?(?:window|browser|chrome|app)$", "minimize the window"),
    # exit fullscreen variants people actually say
    (r"^(?:exit|leave|stop|end)\s+(?:the\s+)?fullscreen$", "exit fullscreen"),
    (r"^fullscreen\s+off$", "exit fullscreen"),
    # skip ad STT leftovers
    (r"^skip\s+(?:the\s+|this\s+|that\s+)?(?:ad|ads)$", "skip the ad"),
    # screen describe
    (r"^what(?:s| is)\s+on\s+(?:my\s+|the\s+)?(?:screen|screens|monitor|monitors)$",
     "what's on my screen"),
]


def _apply_pairs(text: str, pairs: list[tuple[str, str]]) -> str:
    for pattern, repl in pairs:
        text = re.sub(pattern, repl, text, flags=re.I)
    return text


def strip_fillers(text: str) -> str:
    t = text
    for pat in ASSISTANT_LEAD:
        t = re.sub(pat, "", t, flags=re.I).strip()
    for pat in FILLERS:
        t = re.sub(pat, " ", t, flags=re.I)
    for _ in range(4):
        new = t
        for pat in LEAD_INS:
            new = re.sub(pat, "", new, flags=re.I).strip()
        if new == t:
            break
        t = new
    # Re-apply vocative after lead-ins ("hey neuron play…")
    for pat in ASSISTANT_LEAD:
        t = re.sub(pat, "", t, flags=re.I).strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(" .!?")


def clean(raw: str) -> str:
    """Lowercase, strip junk, fix STT mishears, drop fillers."""
    text = (raw or "").lower().strip()
    text = re.sub(r"[^\w\s.']", " ", text)
    text = text.replace("'", "")
    text = _apply_pairs(text, MISHEARS)
    text = strip_fillers(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(" .!?")


def polish(text: str) -> str:
    """Make normal commands consistent (articles, start→open, quit→close)."""
    t = (text or "").strip()
    if not t:
        return t
    t = _apply_pairs(t, NORMALIZERS)
    t = _apply_pairs(t, CONFUSION_FIXES)
    return re.sub(r"\s+", " ", t).strip().rstrip(" .!?")


def paraphrase(text: str) -> str:
    """Backward-compatible name used by brain — now means polish(), not slang."""
    return polish(text)


def understand(raw: str) -> dict:
    """Full NLU pass. Prefer simple normal commands."""
    cleaned = clean(raw)
    canonical = polish(cleaned)
    # Second polish pass for stacked articles
    again = polish(canonical)
    if again:
        canonical = again
    variants = []
    for v in (canonical, cleaned, (raw or "").strip().lower()):
        v = re.sub(r"\s+", " ", (v or "").strip())
        if v and v not in variants:
            variants.append(v)
    return {
        "raw": raw or "",
        "cleaned": cleaned,
        "canonical": canonical,
        "variants": variants,
        "rewrote": canonical != cleaned and bool(canonical),
    }


def best_text(raw: str) -> str:
    info = understand(raw)
    return info["canonical"] or info["cleaned"] or (raw or "")
