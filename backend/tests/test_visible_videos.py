"""Unit tests for viewport-visible YouTube ordinal ordering."""

from __future__ import annotations

import unittest


class FakePage:
    def __init__(self, videos):
        self._videos = videos

    def wait_for_selector(self, *a, **k):
        return None

    def evaluate(self, script, opts=None):
        # Replicate the visibility + sort rules used in browser._collect_watch_videos
        visible_only = bool((opts or {}).get("visibleOnly"))
        limit = int((opts or {}).get("limit") or 30)
        vh = 900
        scored = []
        seen = set()
        for v in self._videos:
            if v["id"] in seen:
                continue
            rect = v["rect"]  # top, left, width, height
            top, left, w, h = rect["top"], rect["left"], rect["width"], rect["height"]
            bottom, right = top + h, left + w
            if w < 100 or h < 60 or right < 160:
                continue
            vis_h = max(0, min(bottom, vh) - max(top, 0))
            vis_w = max(0, min(right, 1600) - max(left, 0))
            ratio = (vis_h * vis_w) / max(1, w * h)
            if visible_only:
                if ratio < 0.55:
                    continue
                if top < -60:
                    continue
            seen.add(v["id"])
            scored.append({**v, "top": top, "left": left, "ratio": ratio})
        scored.sort(key=lambda a: (round(a["top"] / 80), a["left"]))
        return [
            {"href": x["href"], "title": x["title"], "id": x["id"]}
            for x in scored[:limit]
        ]

    def query_selector_all(self, sel):
        return []


class VisibleOrdinalTests(unittest.TestCase):
    def test_skips_half_cut_top_row(self):
        # Mimics the user's screenshot: top row clipped, second row fully visible.
        # 2nd on-screen should be "You're Tony Stark Coding Jarvis".
        videos = [
            {
                "id": "avengers",
                "title": "The Avengers Deleted Scene",
                "href": "https://www.youtube.com/watch?v=avengers",
                "rect": {"top": -120, "left": 220, "width": 360, "height": 280},
            },
            {
                "id": "raja",
                "title": "Why Raja",
                "href": "https://www.youtube.com/watch?v=raja",
                "rect": {"top": -120, "left": 600, "width": 360, "height": 280},
            },
            {
                "id": "ebenezer",
                "title": "Ebenezer Official Trailer",
                "href": "https://www.youtube.com/watch?v=ebenezer",
                "rect": {"top": 180, "left": 220, "width": 360, "height": 280},
            },
            {
                "id": "tony",
                "title": "You're Tony Stark Coding Jarvis",
                "href": "https://www.youtube.com/watch?v=tony",
                "rect": {"top": 180, "left": 600, "width": 360, "height": 280},
            },
            {
                "id": "isro",
                "title": "Scientists Aren't Leaving ISRO",
                "href": "https://www.youtube.com/watch?v=isro",
                "rect": {"top": 180, "left": 980, "width": 360, "height": 280},
            },
        ]
        page = FakePage(videos)
        # Import after defining FakePage; call collector with monkeypatched evaluate path
        import browser

        got = browser._collect_watch_videos(page, limit=10, visible_only=True)
        self.assertEqual([v["id"] for v in got], ["ebenezer", "tony", "isro"])
        self.assertEqual(got[1]["title"], "You're Tony Stark Coding Jarvis")


if __name__ == "__main__":
    unittest.main()
