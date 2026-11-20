"""Resource governor for posting (docs/ARCHITECTURE.md, phase 5): every platform account is a budget with a reset.

Owner, 20 Nov: "prepare a queue that keeps uploading as per the analytics data and its limitations, so we earn from
everywhere". The publish queue asks the governor before every post. Limits make the post WAIT (a quota wait in the
job queue, which costs no attempt); they never fail it and never burst an account.

Budgets (official numbers, with a safety margin; checked 20 Nov 2026):
- YouTube: videos.insert has its own bucket of 100 calls a day per Google project, reset at midnight Pacific
  (developers.google.com/youtube/v3/determine_quota_cost). Splitting uploads over several projects to get more is
  forbidden by the YouTube developer policies, so the only way up is Google's quota-extension audit.
- Instagram: content_publishing_limit is 100 API posts per account per rolling 24 h (some Meta pages still say 50):
  we keep 25.
- Facebook Reels: 30 per Page per 24 h: we keep 25 (the old guard in publish.upload_item).
- Threads: 250 posts per profile per 24 h: we keep 50.
- Dailymotion / Telegram: generous; a small cap only against runaway loops.
Spacing: at most one post per account every MIN_GAP_S (a backlog that clears at once looks like spam and each post
competes with the previous one for the same followers' feed)."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DAY_S = 86400.0
LIMITS = {"instagram": 25, "facebook": 25, "threads": 50, "dailymotion": 40, "telegram": 60}
MIN_GAP_S = {"instagram": 40 * 60, "facebook": 30 * 60, "threads": 20 * 60, "dailymotion": 10 * 60,
             "telegram": 5 * 60, "youtube": 0}


def youtube_reset(now: float | None = None) -> float:
    """Next midnight in Pacific time (when Google resets the YouTube quota)."""
    pt = ZoneInfo("America/Los_Angeles")
    t = datetime.fromtimestamp(now if now is not None else time.time(), pt)
    nxt = datetime(t.year, t.month, t.day, tzinfo=pt) + timedelta(days=1)
    return nxt.timestamp() + 60


class Governor:
    """Counts real posts from the publish log (the platforms' answers are the truth) once, then keeps the counts
    current as the queue posts. One instance per queue run."""

    def __init__(self, log_path: Path | None = None, now: float | None = None, youtube_ok=None):
        self.now = now if now is not None else time.time()
        self.posts: dict[tuple[str, str], list[float]] = {}
        self._youtube_ok = youtube_ok
        if log_path and Path(log_path).exists():
            cut = self.now - DAY_S
            for ln in Path(log_path).read_text(encoding="utf-8").splitlines():
                try:
                    a = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                det = a.get("details") or {}
                if a.get("done") and not det.get("dry_run") and (a.get("at") or 0) > cut and a.get("item_id") \
                        and "Story" not in str(a.get("what") or ""):
                    self.record(a.get("platform") or "", a.get("channel") or "", a.get("at"))

    def record(self, platform: str, channel: str, at: float | None = None) -> None:
        self.posts.setdefault((platform, channel), []).append(float(at if at is not None else self.now))

    def check(self, platform: str, channel: str) -> tuple[bool, float, str]:
        """(may post now, when to try again, why not)."""
        if platform == "youtube":
            ok = self._youtube_ok() if self._youtube_ok else _youtube_quota_ok()
            return (True, 0.0, "") if ok else (False, youtube_reset(self.now), "YouTube upload quota used for today")
        times = sorted(t for t in self.posts.get((platform, channel), []) if t > self.now - DAY_S)
        cap = LIMITS.get(platform)
        if cap and len(times) >= cap:
            return False, times[-cap] + DAY_S + 60, f"{platform} daily limit ({cap} in 24 h) reached"
        gap = MIN_GAP_S.get(platform, 0)
        if gap and times and self.now - times[-1] < gap:
            return False, times[-1] + gap, f"spacing: last {platform} post was {int((self.now - times[-1]) / 60)} min ago"
        return True, 0.0, ""

    def usage(self) -> dict[str, dict[str, int]]:
        """{platform: {channel: posts in the last 24 h}} for the dashboard."""
        out: dict[str, dict[str, int]] = {}
        for (p, c), ts in self.posts.items():
            n = sum(1 for t in ts if t > self.now - DAY_S)
            if n:
                out.setdefault(p, {})[c] = n
        return out


def _youtube_quota_ok() -> bool:
    from ..publish import UPLOAD_UNITS, quota_ok
    return quota_ok(UPLOAD_UNITS, "insert") and quota_ok(50)
