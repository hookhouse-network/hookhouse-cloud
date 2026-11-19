"""What is winning right now in each of our niches: learn from the top creators every week (owner, 12 Nov 2026:
"learn from the top youtube and instagram creators and adapt their strategies").

How: the official YouTube Data API search (no scraping), ordered by YouTube's own view ranking, videos of the last
14 days in each channel's niche (Shorts, and long videos for channels that make them). The titles go into our memory
as "viral examples", so the topic picker and the writer see the packaging that works this month (patterns only;
the writer never copies another creator's words).

YouTube API policy (developer-policies, checked 12 Nov 2026): other channels' data is stored for at most 30 days
(deleted after that), and it is never aggregated across channels (no niche averages or derived scores): each title
is used on its own. Quota: search.list has its own bucket since 1 June 2026 (100 units a call); about 25 calls a week.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from .config import ROOT
from engine.core.http import HTTP

API = "https://www.googleapis.com/youtube/v3"
KEEP_DAYS = 30
SEARCH_UNITS = 100
QUERIES = {   # what a viewer of each channel searches for (first = Shorts, second = long videos)
    "hot_take_hq": ("podcast clip", "podcast highlights"),
    "unsolved_after_dark": ("unsolved mystery", "unsolved mystery documentary"),
    "clutch_tales": ("greatest sports moment", "sports story documentary"),
    "ending_decoded": ("ending explained", "movie ending explained"),
    "money_cheat_codes": ("money explained", "how companies make money"),
    "itihaas_ke_raaz": ("mahabharat ki kahani", "itihaas ke rahasya"),
    "cricket_ke_kisse": ("cricket ke kisse", "cricket story hindi"),
    "picture_abhi_baaki_hai": ("bollywood facts", "bollywood ke kisse"),
    "brain_snack": ("would you rather", "quiz"),
    "bloop_and_friends": ("counting song for kids", "nursery rhymes for kids"),
    "cosmos_unboxed": ("space facts", "space documentary"),
    "deep_blue_files": ("deep sea creatures", "ocean documentary"),
    "wild_instinct": ("wildlife facts", "wildlife documentary"),
    "stream_clips": ("streamer funny moments", "gaming highlights"),
}
TAGS = re.compile(r"\s*#\S+")


def _auth(session=HTTP) -> tuple[dict, dict] | None:
    """An API key (YOUTUBE_API_KEY) or the login of any connected channel."""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        return {"key": key}, {}
    secrets = ROOT / "data" / "secrets"
    from .publish import yt_access_token
    for p in sorted(secrets.glob("youtube_*.json")) if secrets.exists() else []:
        try:
            tok = yt_access_token(p.stem.replace("youtube_", "", 1), session)
        except Exception:  # noqa: BLE001
            tok = None
        if tok:
            return {}, {"Authorization": f"Bearer {tok}"}
    return None


def search(ch: dict, long: bool = False, days: int = 14, n: int = 8, session=HTTP) -> list[dict]:
    """The most-viewed recent videos for the channel's niche: [{id, title, channel, views, published}]."""
    from .publish import add_quota, quota_ok
    auth = _auth(session)
    q = QUERIES.get(ch["id"], (" ".join(t.lstrip("#") for t in (ch.get("hashtags") or [])[:2]),) * 2)[1 if long else 0]
    if not auth or not q or not quota_ok(SEARCH_UNITS, "search"):
        return []
    params, headers = auth
    hindi = ch.get("language") == "hi"
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = session.get(f"{API}/search", headers=headers, timeout=30, params={
        **params, "part": "snippet", "type": "video", "q": q, "order": "viewCount", "publishedAfter": after,
        "maxResults": n, "videoDuration": "medium" if long else "short", "regionCode": "IN" if hindi else "US",
        "relevanceLanguage": "hi" if hindi else "en", "safeSearch": "strict" if ch.get("made_for_kids") else "moderate"})
    add_quota(SEARCH_UNITS, "search")
    r.raise_for_status()
    found = [(it["id"]["videoId"], it["snippet"]) for it in r.json().get("items", []) if it.get("id", {}).get("videoId")]
    if not found:
        return []
    v = session.get(f"{API}/videos", headers=headers, timeout=30,
                    params={**params, "part": "statistics", "id": ",".join(i for i, _ in found)})
    add_quota(1)
    views = {x["id"]: int((x.get("statistics") or {}).get("viewCount") or 0) for x in (v.json().get("items") or [])} \
        if v.ok else {}
    out = []
    for vid, sn in found:
        title = TAGS.sub("", str(sn.get("title") or "")).replace("&#39;", "'").replace("&quot;", '"').replace("&amp;", "&")
        if title.strip():
            out.append({"id": vid, "title": title.strip(), "channel": sn.get("channelTitle", ""),
                        "views": views.get(vid, 0), "published": sn.get("publishedAt", "")})
    return sorted(out, key=lambda x: x["views"], reverse=True)


def purge(memory) -> int:
    """YouTube API policy: other creators' data is never kept longer than 30 days."""
    cut = time.time() - KEEP_DAYS * 86400
    cur = memory.conn.execute("DELETE FROM items WHERE kind='viral_example' AND meta LIKE '%\"source\": \"youtube_search\"%' "
                              "AND created < ?", (cut,))
    memory.conn.commit()
    return cur.rowcount or 0


def refresh(memory, log=print, session=HTTP) -> dict[str, list[dict]]:
    """Weekly: fetch each niche's current winners into memory; returns them for the owner's message."""
    from .config import channels
    from .policy import topic_flags
    purge(memory)
    have = {r[0] for r in memory.conn.execute(
        "SELECT meta FROM items WHERE kind='viral_example' AND meta LIKE '%youtube_search%'").fetchall()}
    report: dict[str, list[dict]] = {}
    for ch in channels():
        if ch.get("active") is False:
            continue
        long_too = int((ch.get("schedule") or {}).get("long_per_week", 0)) > 0
        rows = []
        for long in ((False, True) if long_too else (False,)):
            try:
                got = search(ch, long=long, session=session)
            except Exception as e:  # noqa: BLE001 - one niche failing must not stop the rest
                log(f"  winners {ch['id']}: {e}")
                continue
            for w in got[:5]:
                if topic_flags(w["title"], mode="topic"):          # never-topics stay out of our memory too
                    continue
                w["format"] = "long" if long else "short"
                rows.append(w)
                if any(f'"video_id": "{w["id"]}"' in m for m in have):
                    continue
                memory.add("viral_example", f"{w['title']} ({'long video' if long else 'Short'} by {w['channel']})",
                           channel=ch["id"], performance=float(w["views"]),
                           meta={"source": "youtube_search", "video_id": w["id"], "views": w["views"],
                                 "format": w["format"], "fetched": time.time()})
        if rows:
            report[ch["id"]] = rows
    log(f"Niche winners: {sum(len(v) for v in report.values())} examples for {len(report)} channels")
    return report


def message(report: dict[str, list[dict]], names: dict[str, str]) -> str:
    lines = ["📈 What's winning in your niches this week (YouTube, last 14 days). The writer learns the patterns, "
             "never the words:"]
    for cid, rows in report.items():
        top = sorted(rows, key=lambda r: r["views"], reverse=True)[:2]
        lines.append(f"\n{names.get(cid, cid)}:")
        lines += [f"• {r['title'][:80]} ({r['views']:,} views, {r['format']})" for r in top]
    return "\n".join(lines)[:3900]
