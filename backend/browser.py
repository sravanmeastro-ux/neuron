"""N.E.U.R.O.N browser control.

A dedicated Chrome instance that NEURON drives with Playwright so it can act
inside web pages like a human: navigate, search YouTube, click the Nth video,
click things by text. Reliable because it reads the real page, not pixels.

Playwright's sync API is single-threaded, so all operations run on one
dedicated worker thread and results are marshalled back.
"""

import queue
import re
import threading
import time
import urllib.parse
from pathlib import Path

PROFILE_DIR = str(Path(__file__).resolve().parent / ".neuron-chrome")


def supported() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


class _BrowserWorker:
    def __init__(self):
        self._q = queue.Queue()
        self._ready = threading.Event()
        self._ok = False
        self._err = None
        self._page = None
        self._ctx = None
        self._pw = None
        threading.Thread(target=self._run, daemon=True).start()

    def _launch(self):
        """(Re)start a persistent Chrome context. Called on the worker thread."""
        from playwright.sync_api import sync_playwright

        # Tear down any dead/half-open context first.
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._page = None
        self._pw = None

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            channel="chrome",
            no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._ok = True
        self._err = None

    def _run(self):
        try:
            self._launch()
        except Exception as exc:
            self._err = str(exc)
            self._ok = False
        finally:
            self._ready.set()

        if not self._ok:
            return

        while True:
            job = self._q.get()
            if job is None:
                break
            fn, args, box = job
            try:
                box["value"] = fn(self, *args)
            except Exception as exc:
                msg = str(exc)
                # Chrome was closed by the user / crashed — relaunch once and retry.
                if any(s in msg.lower() for s in (
                    "has been closed", "target closed", "browser has been closed",
                    "context or browser", "connection closed",
                )):
                    try:
                        print("[browser] context dead — relaunching Chrome...", flush=True)
                        self._launch()
                        box["value"] = fn(self, *args)
                    except Exception as exc2:
                        box["error"] = str(exc2)
                else:
                    box["error"] = msg
            box["done"].set()

    def submit(self, fn, *args, timeout=90):
        """Run an operation on the worker thread. Raises on failure so callers
        can never mistake a browser failure for success."""
        self._ready.wait(30)
        if not self._ok:
            raise RuntimeError(f"the browser couldn't start: {self._err or 'unknown'}")
        box = {"done": threading.Event()}
        self._q.put((fn, args, box))
        if not box["done"].wait(timeout):
            raise RuntimeError("that took too long in the browser")
        if "error" in box:
            raise RuntimeError(box["error"])
        return box["value"]


# ---- operations (run on the worker thread; first arg is the worker) ----

def _active_page(w):
    """Return a live page, relaunching Chrome if the user closed it."""
    try:
        alive = w._ctx is not None and not w._ctx.pages is None
        if alive:
            # Touch the context — raises if it was closed.
            _ = w._ctx.pages
            if w._ctx.pages:
                w._page = w._ctx.pages[-1]
                return w._page
            w._page = w._ctx.new_page()
            return w._page
    except Exception:
        alive = False
    # Context gone — relaunch.
    w._launch()
    return w._page


def _dismiss_noise(page):
    """Best-effort dismiss cookie / sign-in / promo overlays that block clicks."""
    candidates = [
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button:has-text("Got it")',
        'button[aria-label="Close"]',
        'tp-yt-paper-button:has-text("Accept all")',
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=400):
                loc.click(timeout=1000)
                time.sleep(0.3)
        except Exception:
            pass


def _op_open(w, url):
    page = _active_page(w)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.bring_to_front()
    _dismiss_noise(page)
    return f"Opened {url}."


def _op_youtube_search(w, query):
    page = _active_page(w)
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.bring_to_front()
    _dismiss_noise(page)
    return f"Searching YouTube for {query}."


def _op_search(w, url, label):
    page = _active_page(w)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.bring_to_front()
    _dismiss_noise(page)
    return label


def _video_id(href: str) -> str:
    if not href:
        return ""
    try:
        parsed = urllib.parse.urlparse(href)
        if "/shorts/" in parsed.path:
            return ""  # skip Shorts — user said "video"
        if parsed.path.startswith("/watch"):
            return urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        # relative /watch?v=...
        if "watch" in href and "v=" in href:
            return urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("v", [""])[0] \
                or urllib.parse.parse_qs(href.split("?", 1)[-1]).get("v", [""])[0]
    except Exception:
        return ""
    return ""


def _collect_watch_videos(page, limit=30, *, visible_only=False, nudge_scroll=False):
    """Return unique homepage/search videos as [{href, title, id}, ...].

    When visible_only=True (ordinal "play the 2nd video"), count only cards that
    are mostly on-screen — matching what the user can see, not DOM order from
    the top of the page (which includes scrolled-off rows).

    Skips Shorts, duplicates, and empty links. Prefer real /watch?v= videos.
    """
    try:
        page.wait_for_selector('a[href*="/watch?v="]', timeout=15000)
    except Exception:
        pass

    # Never auto-scroll when matching what the user sees — that changes the feed.
    if nudge_scroll and not visible_only:
        try:
            time.sleep(0.35)
            page.mouse.wheel(0, 400)
            time.sleep(0.35)
        except Exception:
            pass
    else:
        time.sleep(0.35)

    # Card-first scan: sort by on-screen position (top→bottom, left→right).
    # Prefer title links (#video-title-link) — thumbnail <a> often has no title text.
    script = """
    (opts) => {
      const limit = opts.limit || 30;
      const visibleOnly = !!opts.visibleOnly;
      const vh = window.innerHeight || document.documentElement.clientHeight || 800;
      const vw = window.innerWidth || document.documentElement.clientWidth || 1200;
      const seen = new Set();
      const out = [];

      const cleanTitle = (raw) => {
        let title = (raw || '').replace(/\\s+/g, ' ').trim();
        if (!title) return '';
        // aria-label: "TITLE by CHANNEL 12 minutes 3 seconds 1,234 views"
        const by = title.search(/\\sby\\s/i);
        if (by > 0) title = title.slice(0, by).trim();
        title = title
          .replace(/\\s*\\d{1,2}:\\d{2}(:\\d{2})?\\s*$/g, '')
          .replace(/\\s+/g, ' ')
          .trim();
        if (/^\\d{1,2}:\\d{2}(:\\d{2})?$/.test(title)) return '';
        if (title.length < 2) return '';
        return title.slice(0, 140);
      };

      const pickTitle = (a, item) => {
        const fromEl = (el) => {
          if (!el) return '';
          let t = cleanTitle(el.getAttribute('title') || '');
          if (t) return t;
          t = cleanTitle(el.getAttribute('aria-label') || '');
          if (t) return t;
          t = cleanTitle(el.textContent || el.innerText || '');
          return t;
        };
        let title = fromEl(a);
        if (title) return title;
        if (!item) return '';
        const sels = [
          'a#video-title-link',
          'a#video-title',
          '#video-title-link',
          '#video-title',
          'yt-formatted-string#video-title',
          '#video-title yt-formatted-string',
          'a[href*="/watch?v="]#video-title-link',
          'h3 a[href*="/watch?v="]',
          'h3 yt-formatted-string',
          '[id="video-title"]',
        ];
        for (const s of sels) {
          try {
            title = fromEl(item.querySelector(s));
            if (title) return title;
          } catch (e) {}
        }
        // Last resort: any labelled control inside the card
        try {
          const labeled = item.querySelector('[title], [aria-label]');
          title = fromEl(labeled);
        } catch (e) {}
        return title || '';
      };

      const visibility = (rect) => {
        const visH = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
        const visW = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
        const area = Math.max(1, rect.width * rect.height);
        return (visH * visW) / area;
      };

      // Only top-level cards — NOT nested ytd-rich-grid-media (duplicate / no title).
      let items = Array.from(document.querySelectorAll(
        'ytd-rich-item-renderer, ytd-video-renderer, ytd-grid-video-renderer'
      ));
      if (!items.length) {
        items = Array.from(document.querySelectorAll('a#video-title-link, a#video-title'));
      }

      const scored = [];
      for (const item of items) {
        try {
          // Prefer the TITLE link (has title/aria-label). Thumbnail anchors are often blank.
          let a = null;
          if (item.matches && item.matches('a#video-title-link, a#video-title')) {
            a = item;
          } else {
            a = item.querySelector('a#video-title-link, a#video-title')
              || item.querySelector('h3 a[href*="/watch?v="]')
              || item.querySelector('a[href*="/watch?v="]');
          }
          if (!a) continue;
          const href = a.href || '';
          if (!href || href.includes('/shorts/')) continue;
          const u = new URL(href);
          const id = u.searchParams.get('v');
          if (!id || seen.has(id)) continue;

          const boxEl = (item.getBoundingClientRect && item.tagName && item.tagName.includes('YTD'))
            ? item : a;
          const rect = boxEl.getBoundingClientRect();
          if (rect.width < 80 || rect.height < 40) continue;
          // Skip left rail / mini suggestions
          if (rect.right < 160) continue;

          const ratio = visibility(rect);
          if (visibleOnly) {
            if (ratio < 0.55) continue;
            if (rect.top < -60) continue;
          } else if (ratio <= 0 && rect.bottom < 0) {
            continue;
          }

          const title = pickTitle(a, item);
          seen.add(id);
          scored.push({
            href: u.origin + '/watch?v=' + id,
            title,
            id,
            top: rect.top,
            left: rect.left,
            ratio,
          });
        } catch (e) {}
      }

      scored.sort((a, b) => {
        const rowA = Math.round(a.top / 80);
        const rowB = Math.round(b.top / 80);
        if (rowA !== rowB) return rowA - rowB;
        return a.left - b.left;
      });

      for (const v of scored) {
        out.push({href: v.href, title: v.title, id: v.id});
        if (out.length >= limit) break;
      }
      return out;
    }
    """
    try:
        videos = page.evaluate(script, {"limit": int(limit), "visibleOnly": bool(visible_only)}) or []
    except Exception:
        videos = []

    # Fallback to classic selectors if JS scan found nothing.
    if not videos:
        selectors = [
            "ytd-rich-item-renderer a#video-title-link",
            "ytd-video-renderer a#video-title",
            "a#video-title-link",
            "a#video-title",
        ]
        for sel in selectors:
            try:
                links = page.query_selector_all(sel)
            except Exception:
                continue
            seen = set()
            for link in links:
                try:
                    if visible_only:
                        try:
                            box = link.bounding_box()
                            if not box:
                                continue
                            if box["width"] < 80 or box["height"] < 20:
                                continue
                        except Exception:
                            pass
                    href = link.get_attribute("href") or ""
                    vid = _video_id(href)
                    if not vid or vid in seen:
                        continue
                    if href.startswith("/"):
                        href = "https://www.youtube.com" + href
                    title = (
                        link.get_attribute("title")
                        or link.get_attribute("aria-label")
                        or link.inner_text()
                        or ""
                    ).strip()
                    if " by " in title.lower():
                        title = re.split(r"\sby\s", title, maxsplit=1, flags=re.I)[0].strip()
                    seen.add(vid)
                    videos.append({"href": href, "title": title, "id": vid})
                    if len(videos) >= limit:
                        break
                except Exception:
                    continue
            if videos:
                break

    return videos[:limit]


def _is_youtube_home(url: str) -> bool:
    """True if URL is the YouTube home/feed (not watch/search/shorts)."""
    if "youtube.com" not in (url or ""):
        return False
    u = (url or "").lower()
    if any(x in u for x in ("/watch", "/results", "/shorts/", "/playlist", "/channel", "/@")):
        return False
    path = urllib.parse.urlparse(url).path.rstrip("/") or "/"
    return path in ("/", "") or path.startswith("/feed")


def _is_youtube_list(url: str) -> bool:
    """Home or search results — pages where we can pick an Nth video."""
    u = (url or "").lower()
    if "youtube.com" not in u:
        return False
    if "/watch" in u or "/shorts/" in u:
        return False
    return _is_youtube_home(url) or "/results" in u


def _op_list_visible_videos(w):
    """Count/list videos currently visible on the YouTube page (with titles)."""
    page = _active_page(w)
    page.bring_to_front()
    url = (page.url or "").lower()
    if "youtube.com" not in url:
        raise RuntimeError("YouTube isn't open in the controlled browser.")
    _dismiss_noise(page)
    videos = _collect_watch_videos(page, limit=24, visible_only=True, nudge_scroll=False)
    if not videos:
        time.sleep(0.6)
        videos = _collect_watch_videos(page, limit=24, visible_only=True, nudge_scroll=False)
    if not videos:
        raise RuntimeError("I don't see any video tiles on the YouTube page right now.")

    # If titles are still blank, one Playwright pass on title links only.
    if sum(1 for v in videos if (v.get("title") or "").strip()) < max(1, len(videos) // 2):
        try:
            enriched = page.evaluate(
                """(ids) => {
                  const map = {};
                  for (const a of document.querySelectorAll(
                    'a#video-title-link, a#video-title, h3 a[href*="/watch?v="]'
                  )) {
                    try {
                      const u = new URL(a.href);
                      const id = u.searchParams.get('v');
                      if (!id || !ids.includes(id)) continue;
                      let t = (a.getAttribute('title') || a.getAttribute('aria-label')
                               || a.textContent || '').trim();
                      const by = t.search(/\\sby\\s/i);
                      if (by > 0) t = t.slice(0, by).trim();
                      t = t.replace(/\\s+/g, ' ').slice(0, 140);
                      if (t) map[id] = t;
                    } catch (e) {}
                  }
                  return map;
                }""",
                [v["id"] for v in videos],
            ) or {}
            for v in videos:
                if not (v.get("title") or "").strip() and v["id"] in enriched:
                    v["title"] = enriched[v["id"]]
        except Exception:
            pass

    n = len(videos)
    lines = []
    for i, v in enumerate(videos, 1):
        title = (v.get("title") or "").strip() or f"video {v.get('id', i)}"
        lines.append(f"{i}) {title}")
    spoken = f"I can see {n} video{'s' if n != 1 else ''} on screen: " + "; ".join(lines[:8])
    if n > 8:
        spoken += f"; and {n - 8} more."
    else:
        spoken += "."
    return spoken


def _op_play_result(w, index, force_home=False):
    """Play the Nth video the user can currently see on YouTube.

    Uses viewport-visible cards (what is on screen), not full-page DOM order.
    """
    page = _active_page(w)
    page.bring_to_front()
    url = page.url or ""

    if "youtube.com" not in url:
        page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
    elif force_home:
        # Need the homepage feed — but NEVER refresh if already there.
        if _is_youtube_home(url):
            pass  # already home; do not reload
        elif "/results" in url or "/watch" in url or "/shorts/" in url:
            page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()
        else:
            page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()
    elif "/watch" in url:
        # Asking for Nth video while watching — go home once (user wants a feed pick).
        page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()

    _dismiss_noise(page)
    # Match what is on screen right now (no auto-scroll that shifts the feed).
    videos = _collect_watch_videos(page, limit=24, visible_only=True, nudge_scroll=False)
    if not videos:
        time.sleep(0.8)
        videos = _collect_watch_videos(page, limit=24, visible_only=True, nudge_scroll=False)
    if not videos:
        # Last resort: any cards (still sorted visually), so we don't fail hard.
        videos = _collect_watch_videos(page, limit=24, visible_only=False, nudge_scroll=False)
    if not videos:
        raise RuntimeError("I don't see any videos on this YouTube page yet")
    if index < 1 or index > len(videos):
        titles = "; ".join(
            ((v.get("title") or "").strip() or f"id:{v.get('id', '?')}")[:50]
            for v in videos[:6]
        )
        raise RuntimeError(
            f"I only see {len(videos)} video(s) on screen — asked for #{index}. "
            f"Visible: {titles}."
        )

    target = videos[index - 1]
    # If somehow already on that watch URL, don't reload — just ensure play.
    cur_id = _video_id(page.url or "")
    if cur_id != target["id"]:
        page.goto(target["href"], wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()

    deadline = time.time() + 8
    landed = False
    while time.time() < deadline:
        cur = page.url or ""
        if "/watch" in cur and _video_id(cur) == target["id"]:
            landed = True
            break
        time.sleep(0.25)
    if not landed:
        raise RuntimeError(
            f"I tried to open '{target['title'] or target['id']}' but YouTube didn't play it"
        )

    # Make sure playback actually started (YouTube often lands paused).
    _ensure_playback(page, want="play")

    ordinal = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(
        index, f"{index}th"
    )
    title = target["title"]
    return f"Playing the {ordinal} video on screen" + (f": {title}." if title else ".")


def _op_play_by_title(w, query: str):
    """Play a video whose on-screen title matches what the user said.

    Reads titles from the live YouTube page (home/search/feed), fuzzy-matches
    the spoken name, scrolls to load more if needed, then opens the best hit.
    """
    q = (query or "").strip()
    if len(q) < 2:
        raise RuntimeError("Tell me the video name to play.")

    page = _active_page(w)
    page.bring_to_front()
    url = (page.url or "").lower()
    if "youtube.com" not in url:
        page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
    _dismiss_noise(page)

    def _norm(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"[^\w\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    qn = _norm(q)
    q_words = [w for w in qn.split() if len(w) > 1]

    def _score(title: str) -> float:
        tn = _norm(title)
        if not tn:
            return 0.0
        if qn == tn:
            return 100.0
        if qn in tn or tn in qn:
            return 90.0 + min(9.0, len(qn) / 10.0)
        if not q_words:
            return 0.0
        hits = sum(1 for w in q_words if w in tn)
        # Prefer denser overlap
        return (hits / len(q_words)) * 80.0

    best = None
    best_score = 0.0
    seen_ids = set()
    # Scroll and rescan a few times so titles below the fold are found.
    for attempt in range(5):
        videos = _collect_watch_videos(page, limit=40)
        for v in videos:
            vid = v.get("id") or ""
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            sc = _score(v.get("title") or "")
            if sc > best_score:
                best_score = sc
                best = v
        if best_score >= 55:
            break
        try:
            page.mouse.wheel(0, 1100)
        except Exception:
            pass
        time.sleep(0.55)

    if not best or best_score < 35:
        # List a few visible titles to help the user.
        sample = [v.get("title") for v in (_collect_watch_videos(page, limit=8) or []) if v.get("title")]
        hint = ("; ".join(sample[:5]) if sample else "none visible")
        raise RuntimeError(
            f"I couldn't find a video matching '{q}' on this page. "
            f"Visible titles: {hint}."
        )

    target = best
    cur_id = _video_id(page.url or "")
    if cur_id != target["id"]:
        page.goto(target["href"], wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()

    deadline = time.time() + 8
    landed = False
    while time.time() < deadline:
        cur = page.url or ""
        if "/watch" in cur and _video_id(cur) == target["id"]:
            landed = True
            break
        time.sleep(0.25)
    if not landed:
        raise RuntimeError(
            f"I found '{target.get('title') or q}' but YouTube didn't open it."
        )
    _ensure_playback(page, want="play")
    title = target.get("title") or q
    return f"Playing: {title}."


def _op_youtube_home(w):
    """Navigate to YouTube homepage and STOP — do not play anything."""
    page = _active_page(w)
    page.bring_to_front()
    url = page.url or ""
    if _is_youtube_home(url):
        # Already home — soft refresh can restart autoplay; just confirm.
        try:
            page.bring_to_front()
        except Exception:
            pass
        return "Already on the YouTube homepage."
    page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=30000)
    page.bring_to_front()
    return "Back on the YouTube homepage."


def _op_youtube_home_play(w, index):
    """Play the Nth video from the YouTube homepage (no reload if already home)."""
    return _op_play_result(w, index, force_home=True)


def _ensure_playback(page, want: str = "play") -> str:
    """Play or pause the YouTube <video> without toggling twice.

    Root cause of play/pause flicker: clicking the player toggles, then
    pressing 'k' toggles again — net pause. Here we read paused state and
    only change it if needed.
    """
    want = (want or "play").lower()
    script = """
    (want) => {
      const v = document.querySelector('video.html5-main-video, video');
      if (!v) return {ok: false, reason: 'no-video'};
      const paused = !!v.paused;
      if (want === 'play') {
        if (!paused) return {ok: true, did: 'already-playing'};
        const p = v.play();
        if (p && p.then) p.catch(() => {});
        return {ok: true, did: 'play'};
      }
      if (want === 'pause' || want === 'stop') {
        if (paused) return {ok: true, did: 'already-paused'};
        v.pause();
        return {ok: true, did: 'pause'};
      }
      return {ok: false, reason: 'bad-want'};
    }
    """
    try:
        result = page.evaluate(script, want) or {}
    except Exception as exc:
        raise RuntimeError(f"couldn't control the player: {exc}")
    if not result.get("ok"):
        # Fallback: click the big center play/pause button once.
        try:
            if want == "play":
                btn = page.locator("button.ytp-large-play-button, button.ytp-play-button").first
                if btn.count():
                    # Only if paused — check aria
                    label = (btn.get_attribute("aria-label") or "").lower()
                    if "pause" not in label:
                        btn.click(timeout=1500, force=True)
                        return "Playing the video."
            else:
                btn = page.locator("button.ytp-play-button").first
                if btn.count():
                    label = (btn.get_attribute("aria-label") or "").lower()
                    if "play" not in label or "pause" in label:
                        btn.click(timeout=1500, force=True)
                        return "Paused the video."
        except Exception:
            pass
        raise RuntimeError("I couldn't find the YouTube player")
    did = result.get("did")
    if did == "already-playing":
        return "The video is already playing."
    if did == "already-paused":
        return "The video is already paused."
    if did == "play":
        return "Playing the video."
    if did == "pause":
        return "Paused the video."
    return "Done."


def _op_ensure_playback(w, want: str = "play"):
    page = _active_page(w)
    page.bring_to_front()
    try:
        for p in w._ctx.pages:
            u = (p.url or "").lower()
            if "youtube.com" in u and ("/watch" in u or "/shorts/" in u):
                p.bring_to_front()
                page = p
                w._page = p
                break
    except Exception:
        pass
    url = (page.url or "").lower()
    if "youtube.com" not in url or ("/watch" not in url and "/shorts/" not in url):
        # Still try if a player exists on the page
        try:
            if not page.locator("video.html5-main-video, video").count():
                raise RuntimeError("Open a YouTube video first")
        except Exception:
            raise RuntimeError("Open a YouTube video first")
    return _ensure_playback(page, want)


def _op_skip_ad(w):
    """Click YouTube's Skip Ad / Skip Ads control if one is visible."""
    page = _active_page(w)
    page.bring_to_front()
    url = page.url or ""
    if "youtube.com" not in url:
        raise RuntimeError("YouTube isn't open — open a video first")

    # Poll briefly: the Skip button often appears a few seconds into the ad.
    selectors = [
        "button.ytp-skip-ad-button",
        "button.ytp-ad-skip-button",
        "button.ytp-ad-skip-button-modern",
        ".ytp-skip-ad-button",
        ".ytp-ad-skip-button-modern",
        "button:has-text('Skip')",
        "button:has-text('Skip Ad')",
        "button:has-text('Skip Ads')",
        ".ytp-ad-skip-button-container button",
    ]
    deadline = time.time() + 12
    while time.time() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                if not loc.is_visible(timeout=300):
                    continue
                loc.click(timeout=2000, force=True)
                time.sleep(0.4)
                return "Skipped the ad."
            except Exception:
                continue
        # Also try role-based name match
        try:
            btn = page.get_by_role("button", name=re.compile(r"skip\s*ads?", re.I)).first
            if btn.count() and btn.is_visible(timeout=300):
                btn.click(timeout=2000, force=True)
                return "Skipped the ad."
        except Exception:
            pass
        time.sleep(0.45)

    # No skip button — maybe there is no ad, or it's unskippable yet.
    try:
        has_ad = page.locator(".ad-showing, .ytp-ad-player-overlay, .ytp-ad-module").count() > 0
    except Exception:
        has_ad = False
    if has_ad:
        raise RuntimeError("There's an ad, but the Skip button isn't available yet")
    return "I don't see an ad to skip right now."


def _op_player_key(w, key: str):
    """Send a YouTube player shortcut. For play/pause use ensure_playback instead of 'k'."""
    page = _active_page(w)
    page.bring_to_front()
    try:
        for p in w._ctx.pages:
            u = (p.url or "").lower()
            if "youtube.com" in u and ("/watch" in u or "/shorts/" in u):
                p.bring_to_front()
                page = p
                w._page = p
                break
    except Exception:
        pass
    # Focus without toggling: click an inert chrome area, not the video.
    try:
        page.locator("#movie_player").first.focus(timeout=500)
    except Exception:
        pass
    page.keyboard.press(key)
    labels = {
        "m": "Toggled mute on YouTube.",
        "Shift+N": "Next YouTube video.",
        "Shift+P": "Previous YouTube video.",
        "f": "YouTube is fullscreen.",
        "Escape": "Exited fullscreen.",
        "i": "YouTube miniplayer on.",
        "t": "Toggled YouTube theater mode.",
        "c": "Toggled captions.",
    }
    return labels.get(key, f"Pressed {key} on the player.")


def _youtube_watch_page(w):
    """Bring a YouTube watch/shorts tab to front if one exists."""
    page = _active_page(w)
    page.bring_to_front()
    try:
        for p in w._ctx.pages:
            u = (p.url or "").lower()
            if "youtube.com" in u and ("/watch" in u or "/shorts/" in u):
                p.bring_to_front()
                w._page = p
                return p
    except Exception:
        pass
    return page


def _focus_youtube_player(page):
    try:
        player = page.locator("#movie_player, .html5-video-player, video.html5-main-video").first
        if player.count():
            player.click(timeout=1500, force=True, position={"x": 40, "y": 40})
            time.sleep(0.12)
            return True
    except Exception:
        pass
    try:
        page.locator("#movie_player").first.focus(timeout=500)
        return True
    except Exception:
        return False


def _op_fullscreen(w, exit_fs=False):
    """Enter/exit content fullscreen in the controlled browser.

    YouTube: press 'f' (player fullscreen) — NOT the Windows maximize shortcut.
    Exit: focus player, Escape, and click Exit if still fullscreen. Also leaves
    theater/cinema mode when the user asked to exit a 'big' video view.
    Other sites: try the Fullscreen control, else F11 (browser fullscreen).
    """
    page = _youtube_watch_page(w)
    url = (page.url or "").lower()

    on_youtube = "youtube.com" in url and ("/watch" in url or "/shorts/" in url)
    if not on_youtube:
        try:
            if page.locator("video.html5-main-video, #movie_player").count():
                on_youtube = True
        except Exception:
            pass

    if exit_fs:
        _focus_youtube_player(page)
        # Prefer the explicit Exit control when present.
        try:
            fs = page.locator(
                "button.ytp-fullscreen-button[title*='Exit' i], "
                "button.ytp-fullscreen-button[aria-label*='Exit' i]"
            ).first
            if fs.count():
                fs.click(timeout=1500, force=True)
                time.sleep(0.2)
                return "Exited fullscreen."
        except Exception:
            pass
        page.keyboard.press("Escape")
        time.sleep(0.2)
        # Still fullscreen? toggle with f.
        try:
            fs = page.locator("button.ytp-fullscreen-button").first
            if fs.count():
                label = (fs.get_attribute("title") or fs.get_attribute("aria-label") or "").lower()
                if "exit" in label:
                    page.keyboard.press("f")
                    time.sleep(0.2)
                    return "Exited fullscreen."
        except Exception:
            pass
        # Theater/cinema looks "big" — leave it if still large view.
        try:
            th = page.locator("button.ytp-size-button").first
            if th.count():
                label = (th.get_attribute("title") or th.get_attribute("aria-label") or "").lower()
                if "default" in label:  # currently in theater → "Default view"
                    page.keyboard.press("t")
                    time.sleep(0.15)
                    return "Left theater mode (you weren't in fullscreen)."
        except Exception:
            pass
        return "Exited fullscreen."

    if on_youtube:
        _focus_youtube_player(page)
        page.keyboard.press("f")
        time.sleep(0.35)
        try:
            fs = page.locator("button.ytp-fullscreen-button").first
            if fs.count():
                label = (fs.get_attribute("title") or fs.get_attribute("aria-label") or "").lower()
                if "exit" not in label:
                    fs.click(timeout=1500, force=True)
        except Exception:
            pass
        return "YouTube is fullscreen."

    for sel in (
        "button[aria-label*='Full screen' i]",
        "button[title*='Full screen' i]",
        "button:has-text('Fullscreen')",
        "button:has-text('Full screen')",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=400):
                loc.click(timeout=2000, force=True)
                return "Fullscreen."
        except Exception:
            continue
    page.keyboard.press("F11")
    return "Tried browser fullscreen (F11)."


def _op_miniplayer(w):
    """YouTube miniplayer (keyboard 'i') — never minimize the Chrome window."""
    page = _youtube_watch_page(w)
    _focus_youtube_player(page)
    # Explicit Miniplayer control when visible.
    try:
        btn = page.locator(
            "button.ytp-miniplayer-button, "
            "button[title*='Miniplayer' i], "
            "button[aria-label*='Miniplayer' i]"
        ).first
        if btn.count() and btn.is_visible(timeout=400):
            btn.click(timeout=1500, force=True)
            time.sleep(0.2)
            return "Video is in miniplayer."
    except Exception:
        pass
    page.keyboard.press("i")
    time.sleep(0.25)
    return "Video is in miniplayer."


def _op_page_scroll(w, direction: str = "down", amount: int = 900):
    """Scroll the active browser page (YouTube feed, search, etc.)."""
    page = _active_page(w)
    page.bring_to_front()
    dy = abs(int(amount)) if direction == "down" else -abs(int(amount))
    try:
        page.mouse.wheel(0, dy)
    except Exception:
        pass
    time.sleep(0.12)
    try:
        page.keyboard.press("PageDown" if direction == "down" else "PageUp")
    except Exception:
        pass
    return f"Scrolled {direction}."


def _op_close_browser(w):
    """Shut down the controlled Chrome window/context."""
    try:
        if w._page is not None:
            try:
                w._page.bring_to_front()
            except Exception:
                pass
    except Exception:
        pass
    try:
        if w._ctx is not None:
            w._ctx.close()
    except Exception:
        pass
    try:
        if w._pw is not None:
            w._pw.stop()
    except Exception:
        pass
    w._ctx = None
    w._page = None
    w._pw = None
    w._ok = False
    return "Closed Chrome."


def _op_click_text(w, text):
    page = _active_page(w)
    page.bring_to_front()
    _dismiss_noise(page)
    try:
        page.get_by_text(text, exact=False).first.click(timeout=6000)
        return f"Clicked {text}."
    except Exception:
        try:
            page.get_by_role("link", name=text).first.click(timeout=6000)
            return f"Clicked {text}."
        except Exception:
            raise RuntimeError(f"I couldn't find '{text}' on this page")


_worker = None
_lock = threading.Lock()


def _get():
    global _worker
    with _lock:
        if _worker is None:
            _worker = _BrowserWorker()
    return _worker


def _op_learn_snapshot(w, site_hint: str = ""):
    """Capture URL/title/labels from the controlled browser page for learning."""
    page = _active_page(w)
    page.bring_to_front()
    hint = (site_hint or "").strip().lower()
    if hint in ("yt",):
        hint = "youtube"
    # Navigate only if we're not already on the requested site.
    if hint:
        try:
            import actions as _actions
            want = _actions._resolve_site_url(hint)
            cur = (page.url or "").lower()
            domain = want.split("//", 1)[-1].split("/", 1)[0].lower()
            if domain and domain not in cur:
                page.goto(want, wait_until="domcontentloaded", timeout=30000)
                time.sleep(0.8)
                _dismiss_noise(page)
        except Exception:
            pass
    else:
        _dismiss_noise(page)

    script = """
    () => {
      const labels = [];
      const seen = new Set();
      const push = (t) => {
        t = (t || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
        if (!t || t.length < 2) return;
        const k = t.toLowerCase();
        if (seen.has(k)) return;
        seen.add(k);
        labels.push(t);
      };
      for (const el of document.querySelectorAll(
        'a, button, input, textarea, [role="button"], [role="tab"], [aria-label], ytd-guide-entry-renderer'
      )) {
        push(el.getAttribute('aria-label'));
        push(el.getAttribute('title'));
        push(el.innerText);
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          push(el.getAttribute('placeholder'));
          push(el.value);
        }
        if (labels.length >= 90) break;
      }
      return {
        url: location.href,
        title: document.title || '',
        labels,
        isYouTube: location.hostname.includes('youtube.com'),
        path: location.pathname || '',
      };
    }
    """
    try:
        data = page.evaluate(script) or {}
    except Exception as exc:
        raise RuntimeError(f"couldn't read the page: {exc}")
    data["url"] = data.get("url") or (page.url or "")
    data["title"] = data.get("title") or ""
    return data


def _op_current_url(w):
    page = _active_page(w)
    try:
        page.bring_to_front()
    except Exception:
        pass
    return page.url or ""


def open_site(url: str) -> str:
    return _get().submit(_op_open, url)


def youtube_search(query: str) -> str:
    return _get().submit(_op_youtube_search, query)


def search(url: str, label: str) -> str:
    return _get().submit(_op_search, url, label)


def play_result(index: int) -> str:
    return _get().submit(_op_play_result, index, False)


def youtube_home() -> str:
    """Go to YouTube homepage only — never plays a video."""
    return _get().submit(_op_youtube_home)


def youtube_home_play(index: int) -> str:
    """Open YouTube homepage and play the Nth video. Preferred for
    'play the Nth video on the youtube homepage'."""
    return _get().submit(_op_youtube_home_play, index)


def play_by_title(title: str) -> str:
    """Play a visible YouTube video by spoken/on-screen title (not by number)."""
    return _get().submit(_op_play_by_title, title or "")


def list_visible_videos() -> str:
    """Say how many YouTube videos are on screen and list their titles."""
    return _get().submit(_op_list_visible_videos)


def skip_ad() -> str:
    return _get().submit(_op_skip_ad)


def fullscreen(exit_fs: bool = False) -> str:
    return _get().submit(_op_fullscreen, exit_fs)


def miniplayer() -> str:
    """Shrink the YouTube video into miniplayer — NEVER minimize the browser window."""
    return _get().submit(_op_miniplayer)


def player_key(key: str) -> str:
    return _get().submit(_op_player_key, key)


def ensure_playback(want: str = "play") -> str:
    """Play or pause without toggling. want='play'|'pause'|'stop'."""
    return _get().submit(_op_ensure_playback, want)


def page_scroll(direction: str = "down", amount: int = 900) -> str:
    """Scroll the controlled browser page (YouTube home/search/watch)."""
    d = "up" if str(direction).lower().startswith("u") else "down"
    return _get().submit(_op_page_scroll, d, int(amount))


def click_text(text: str) -> str:
    return _get().submit(_op_click_text, text)


def close_browser() -> str:
    """Close NEURON's controlled Chrome. Next open will relaunch it."""
    global _worker
    with _lock:
        worker = _worker
        _worker = None
    if worker is None:
        return "Chrome isn't open."
    try:
        return worker.submit(_op_close_browser, timeout=20)
    except Exception as exc:
        return f"Closed Chrome ({exc})."


def current_url() -> str:
    return _get().submit(_op_current_url)


def learn_snapshot(site_hint: str = "") -> dict:
    """Read the controlled page (optionally navigate to site_hint first)."""
    return _get().submit(_op_learn_snapshot, site_hint or "")


def on_youtube() -> bool:
    try:
        return "youtube.com" in (current_url() or "").lower()
    except Exception:
        return False
