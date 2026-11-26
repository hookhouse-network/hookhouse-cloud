"""Fresh, news-driven topics (owner 18 Nov 2026: "Cricket Ke Kisse should take the topics from the latest news of
cricket or target audience so the content will be relevant and in trending").

The weekly plan fixes topics days ahead, so nothing reacted to this week's matches. Every morning, for channels whose
audience follows the news, the next 1-2 videos not made yet get a topic tied to the last 48 hours of headlines
(Google News RSS search feeds: public, headlines + links only, no scraping, no key). The angle stays the channel's own
format: today's news is the hook, the story behind it (a record, a rivalry, a comeback, history) is the video. The
writer's fact-check still runs on every script.
"""
from __future__ import annotations
from engine.core.quiet import noted

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
    # 24 Nov (owner 23 Nov: "you are taking too old trending topics"): over the last two weeks' plans only 42% of story
    # slots had a real "why now" (Wild Instinct 0 of 16, Deep Blue 31%, Unsolved 37%, Ending Decoded 43%). Queries
    # tried on the live feed first (24 Nov 02:50): e.g. "Impossible volcanic eruption spotted in deepest part of the
    # ocean", "New species of flying frog discovered", "150-year mystery of a Westminster Abbey skeleton may be
    # solved", the weekend box office. "unsolved mystery" returned live missing-person cases: not used.
    "wild_instinct": [("new species discovered OR animal behavior study OR wildlife scientists when:2d", "en-US", "US", "en")],
    "deep_blue_files": [("deep sea OR ocean discovery OR shipwreck OR marine biologists when:2d", "en-US", "US", "en")],
    "unsolved_after_dark": [("mystery archaeologists when:3d", "en-US", "US", "en"),
                            ("historical mystery solved when:3d", "en-US", "US", "en")],
    "ending_decoded": [("box office weekend OR movie ending explained OR streaming top 10 movies when:2d", "en-US", "US",
                        "en")],
}
REFRESH_PER_DAY = 2
AHEAD_H = 48

PROMPT = """You plan the next video for "{name}" ({niche}; audience: {audience}; language: {language}).
The channel's format: {format}
Latest headlines (last 48 hours):
{headlines}

Pick the ONE headline with the strongest pull for this audience right now and turn it into a video topic in the channel's
format: today's news is the hook, the video tells the true, dramatic story behind it (a record, a rivalry, a comeback,
the history that explains it). No rumours, nothing unverified, no real match footage or film clips. Never a live
case: no person who is still missing, no ongoing investigation or trial, no crime with recent victims.
Avoid these recent topics: {avoid}
Reply with JSON only: {{"topic": "...", "angle": "...", "why": "...", "feeling": "{feelings}",
"headline": "the headline you used"}}"""


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
        except Exception as _swallowed:  # noqa: BLE001 - one feed down: the other still counts
            noted("news_topics.py:81", _swallowed)
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
    # 24 Nov: the 17-foot sixgill shark headline became Deep Blue's 25 AND 26 Nov topics and Wild Instinct's 26 Nov one:
    # a used headline was only left out by its exact text, and the model hands it back in other capitals. Now a used
    # story (similar wording) is left out for every channel in this run, and a pick that repeats a topic is refused.
    used: list[str] = []
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
        for start, it in items:
            lines = "\n".join(f"- {h['title']}" + (f" ({h['source']})" if h["source"] else "") for h in news
                              if not weekly.topic_repeats(h["title"], used))
            if not lines:
                log(f"news topics {cid}: every headline is used already")
                break
            prompt = PROMPT.format(name=ch["name"], niche=ch.get("niche", ""),
                                   audience="Indian viewers" if ch.get("market") == "IN" else "United States viewers",
                                   language="Hindi (Roman Hinglish hooks)" if ch.get("language") == "hi" else "English",
                                   format=str(ch.get("writer_rules") or ch.get("bio") or "")[:400], headlines=lines,
                                   avoid="; ".join(avoid[:15]) or "none", feelings="|".join(weekly.FEELINGS))
            try:
                pick, _res = brain.ask_json("writer", prompt, temperature=0.5)
            except Exception as e:  # noqa: BLE001 - the planned topic stays
                log(f"news topics {cid}: {type(e).__name__}: {e}")
                break
            topic = str((pick or {}).get("topic") or "").strip()
            if not topic:
                continue
            headline = str(pick.get("headline") or "")[:200]
            dup = weekly.topic_repeats(headline, used) or weekly.topic_repeats(topic, avoid)
            if dup:
                log(f"news topics {cid}: {it['id']} keeps its topic (the pick repeats '{dup[:60]}')")
                continue
            feeling = str(pick.get("feeling") or "").strip().lower()
            used.append(headline)
            # 24 Nov: the new topic's own hook and feeling, never the replaced topic's ('why now: Trending search
            # "Taylor Sheridan"' reached the writer of an Nvidia video)
            autopilot.update_item(start, it["id"], topic=topic, angle=str(pick.get("angle") or it.get("angle") or ""),
                                  why=str(pick.get("why") or ""), news=headline, planned_topic=it.get("topic"),
                                  now_hook=f"in the news: {headline}" if headline else None,
                                  feeling=feeling if feeling in weekly.FEELINGS else None)
            avoid.insert(0, topic)
            n += 1
            log(f"news topic for {it['id']}: {topic[:80]}")
    return n
