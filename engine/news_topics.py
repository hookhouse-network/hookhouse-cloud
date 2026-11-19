"""Fresh, news-driven topics (owner 18 Nov 2026: "Cricket Ke Kisse should take the topics from the latest news of
cricket or target audience so the content will be relevant and in trending").

The weekly plan fixes topics days ahead, so nothing reacted to this week's matches. Every morning, for channels whose
audience follows the news, the next 1-2 videos not made yet get a topic tied to the last 48 hours of headlines
(Google News RSS search feeds: public, headlines + links only, no scraping, no key). The angle stays the channel's own
format: today's news is the hook, the story behind it (a record, a rivalry, a comeback, history) is the video. The
writer's fact-check still runs on every script.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

GN = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
# channel -> [(query, hl, gl, lang)]
FEEDS = {
    "cricket_ke_kisse": [("cricket when:2d", "hi", "IN", "hi"), ("cricket india when:2d", "en-IN", "IN", "en")],
    "picture_abhi_baaki_hai": [("bollywood when:2d", "hi", "IN", "hi"), ("bollywood box office when:2d", "en-IN", "IN", "en")],
    "clutch_tales": [("NBA OR NFL OR MLB when:2d", "en-US", "US", "en")],
    "cosmos_unboxed": [("NASA OR ISRO OR SpaceX when:2d", "en-US", "US", "en")],
    "money_cheat_codes": [("stock market OR AI company earnings when:2d", "en-US", "US", "en")],
}
REFRESH_PER_DAY = 2
AHEAD_H = 48

PROMPT = """You plan the next video for "{name}" ({niche}; audience: {audience}; language: {language}).
The channel's format: {format}
Latest headlines (last 48 hours):
{headlines}

Pick the ONE headline with the strongest pull for this audience right now and turn it into a video topic in the channel's
format: today's news is the hook, the video tells the true, dramatic story behind it (a record, a rivalry, a comeback,
the history that explains it). No rumours, nothing unverified, no real match footage or film clips.
Avoid these recent topics: {avoid}
Reply with JSON only: {{"topic": "...", "angle": "...", "why": "...", "headline": "the headline you used"}}"""


def parse(xml: str, limit: int = 40) -> list[dict]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S)[:limit]:
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        s = re.search(r"<source[^>]*>(.*?)</source>", item, re.S)
        title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1) if t else "")).strip()
        if not title:
            continue
        try:
            when = parsedate_to_datetime(d.group(1)) if d else None
        except (TypeError, ValueError):
            when = None
        out.append({"title": title, "source": html.unescape(s.group(1)).strip() if s else "", "at": when})
    return out


def headlines(cid: str, hours: int = 48, session=None) -> list[dict]:
    import requests
    session = session or requests
    seen, out = set(), []
    for q, hl, gl, lang in FEEDS.get(cid, []):
        try:
            r = session.get(GN.format(q=quote(q), hl=hl, gl=gl, lang=lang), timeout=20,
                            headers={"User-Agent": "Mozilla/5.0 (HookHouse planner)"})
            items = parse(r.text)
        except Exception:  # noqa: BLE001 - one feed down: the other still counts
            continue
        for it in items:
            key = re.sub(r"\W+", " ", it["title"].lower())[:60]
            fresh = it["at"] is None or it["at"] >= datetime.now(it["at"].tzinfo) - timedelta(hours=hours)
            if key not in seen and fresh:
                seen.add(key)
                out.append(it)
    return out[:30]


def due_items(cid: str, now=None) -> list[tuple[str, dict]]:
    """The channel's next not-yet-made Shorts within AHEAD_H hours that have not been refreshed yet."""
    from . import autopilot, weekly
    now = now or autopilot._now()
    out = []
    for start, it in autopilot.items(0, 3):
        if it.get("channel") != cid or it.get("kind") != "short" or it.get("news") or it["status"] not in weekly.TO_MAKE:
            continue
        if now < autopilot._when(it) <= now + timedelta(hours=AHEAD_H):
            out.append((start, it))
    out.sort(key=lambda x: x[1]["publish_at"])
    return out[:REFRESH_PER_DAY]


def refresh(brain=None, log=print, session=None) -> int:
    """Morning job: news-driven topics for the next videos of the FEEDS channels."""
    from . import autopilot, weekly
    from .config import channel
    if brain is None:
        brain = autopilot.default_brain()[0]
    n = 0
    for cid in FEEDS:
        items = due_items(cid)
        if not items:
            continue
        news = headlines(cid, session=session)
        if not news:
            log(f"news topics {cid}: no headlines")
            continue
        ch = channel(cid)
        avoid = weekly.past_topics(cid, limit=25)
        used: list[str] = []
        for start, it in items:
            lines = "\n".join(f"- {h['title']}" + (f" ({h['source']})" if h["source"] else "") for h in news
                              if h["title"] not in used)
            prompt = PROMPT.format(name=ch["name"], niche=ch.get("niche", ""),
                                   audience="Indian viewers" if ch.get("market") == "IN" else "United States viewers",
                                   language="Hindi (Roman Hinglish hooks)" if ch.get("language") == "hi" else "English",
                                   format=str(ch.get("writer_rules") or ch.get("bio") or "")[:400], headlines=lines,
                                   avoid="; ".join(avoid[:15]) or "none")
            try:
                pick, _res = brain.ask_json("writer", prompt, temperature=0.5)
            except Exception as e:  # noqa: BLE001 - the planned topic stays
                log(f"news topics {cid}: {type(e).__name__}: {e}")
                break
            topic = str((pick or {}).get("topic") or "").strip()
            if not topic:
                continue
            used.append(str(pick.get("headline") or ""))
            autopilot.update_item(start, it["id"], topic=topic, angle=str(pick.get("angle") or it.get("angle") or ""),
                                  why=str(pick.get("why") or ""), news=str(pick.get("headline") or "")[:200],
                                  planned_topic=it.get("topic"))
            avoid.insert(0, topic)
            n += 1
            log(f"news topic for {it['id']}: {topic[:80]}")
    return n
