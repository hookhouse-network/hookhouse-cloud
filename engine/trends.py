"""Trend radar: what people are looking up right now, from official free feeds (no scraping, no keys).

Sources (research_notes/Channel growth and earnings plan/github_money_repos_2026-11-10.md, idea from TrendRadar /
Agent-Reach, rebuilt on official feeds only):
- Wikipedia pageviews API: yesterday's most-read articles on English and Hindi Wikipedia, kept only when they
  really spike (yesterday vs the article's usual daily views), so evergreen pages like "dog" or "Instagram" drop out
- Google Trends daily RSS: top searches in the US and India
- (later, with the owner's key) YouTube "mostPopular" chart per region

Every item passes the never-topics list (config/never_topics.yaml, strict "trend" mode: adult, gambling, fresh
tragedies, politics, allegations about living people...). Then one AI call a day picks, per channel, the few trends
that make a real on-brand video and suggests the angle. Without an AI model, a simple embedding match is used.
The week planner gets these as topic hints; the writer still checks fit, facts and the channel rules.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests
import requests.adapters

from .config import ROOT, channels
from .policy import topic_flags

STATE = ROOT / "data" / "state" / "trends"
WIKI_TOP = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/{d:%Y/%m/%d}"
WIKI_DAILY = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/"
              "{title}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
GT_RSS = "https://trends.google.com/trending/rss?geo={geo}"
SPIKE_MIN = 1.6                      # yesterday must be at least 1.6x the article's usual day

SITE_PAGES = re.compile(r"^(Main_Page|Special:|Wikipedia:|Portal:|File:|Help:|Category:|Template:|Talk:|User:|"
                        r"Deaths_in_|List_of_|\.[a-z]{2,6}$|मुखपृष्ठ|विशेष:|विकिपीडिया:)", re.I)
EXTRA_NEWS = re.compile(r"killed|murder of|death of|assassinat|riot|war crime|हत्या|हमला|political|minister|"
                        r"president of|\bMP\b", re.I)    # trend-only extras on top of the never-topics list

ASSIGN_PROMPT = """You plan topics for faceless YouTube story channels. Today's trending items (index: title - what it
is - source and size):
{items}

Channels:
{channels}

For each channel, pick at most 3 items that could become a great, TRUE, on-brand story video for that channel's
audience (US channels: US/English items; Indian channels: Indian/Hindi items or global items Indians care about).
Skip items that are only celebrity gossip, product launches, sports scores, or anything touching these rules:
{rules}
It is fine to pick nothing for a channel. Return ONLY JSON:
{{"channel_id": [{{"i": 3, "angle": "one-line video angle that fits the channel"}}]}}"""


def _ua() -> dict:
    from .media.visuals import UA
    return UA


_SESSION: requests.Session | None = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:                                  # one kept-alive connection pool (new TLS per call was ~5 s)
        _SESSION = requests.Session()
        _SESSION.headers.update(_ua())
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8)
        _SESSION.mount("https://", adapter)
    return _SESSION


def _get(url: str, **kw):
    r = _session().get(url, timeout=30, **kw)
    r.raise_for_status()
    return r


def _parallel(fn, items: list, workers: int = 4) -> None:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fn, items))


# ---------- sources ----------

def wikipedia_top(project: str, day: date, limit: int = 40) -> list[dict]:
    """Most-read articles of one day (project: en.wikipedia / hi.wikipedia), site pages removed."""
    data = _get(WIKI_TOP.format(project=project, d=day)).json()
    arts = (data.get("items") or [{}])[0].get("articles", [])
    out = []
    for a in arts:
        title = a.get("article", "")
        if SITE_PAGES.match(title):
            continue
        out.append({"source": f"wikipedia:{project.split('.')[0]}", "title": title.replace("_", " "),
                    "key": title, "score": int(a.get("views", 0)), "lang": project.split(".")[0]})
        if len(out) >= limit:
            break
    return out


def wikipedia_spikes(items: list[dict], day: date) -> None:
    """spike = yesterday's views / median daily views over the 30 days before. Evergreen pages score ~1, real
    trends 2-100+. A brand-new page (under a week of history) counts as a trend; a failed lookup does not."""
    def one(it):
        url = WIKI_DAILY.format(project=f"{it['lang']}.wikipedia", title=quote(it["key"], safe=""),
                                start=day - timedelta(days=30), end=day - timedelta(days=1))
        try:
            r = _session().get(url, timeout=30)
            if r.status_code == 404:                      # no history at all: a brand-new article
                it["spike"] = 99.0
                return
            r.raise_for_status()
            views = [x.get("views", 0) for x in r.json().get("items", [])]
            base = statistics.median(views) if len(views) >= 7 else 0
            it["spike"] = round(it["score"] / base, 1) if base else 99.0
        except (requests.RequestException, ValueError):
            it["spike"] = 0.0                             # unknown: don't treat as a trend
    _parallel(one, [it for it in items if it["source"].startswith("wikipedia")])


def wikipedia_describe(items: list[dict]) -> None:
    """Short description + first sentence (for safety and channel fit)."""
    def one(it):
        try:
            s = _get(WIKI_SUMMARY.format(lang=it["lang"], title=quote(it["key"], safe=""))).json()
            it["desc"] = (s.get("description") or "").strip()
            it["extract"] = (s.get("extract") or "").strip()[:300]
        except (requests.RequestException, ValueError):
            it["desc"], it["extract"] = "", ""
    _parallel(one, [it for it in items if it["source"].startswith("wikipedia")])


def google_trends(geo: str) -> list[dict]:
    """Today's top searches for a country from the public Google Trends RSS feed."""
    return parse_trends_rss(_get(GT_RSS.format(geo=geo)).text, geo)


def youtube_popular(region: str, limit: int = 25) -> list[dict]:
    """What is trending on YouTube itself today (official Data API chart, 1 quota unit). 19 Nov (owner: "our content
    looks outdated, not trending"): the topics and formats viewers are watching right now, as ideas for our angles."""
    import os
    key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("YT_KEY")
    if not key:
        return []
    r = _get("https://www.googleapis.com/youtube/v3/videos", params={
        "part": "snippet,statistics", "chart": "mostPopular", "regionCode": region, "maxResults": limit, "key": key})
    out = []
    for v in r.json().get("items") or []:
        sn, st = v.get("snippet") or {}, v.get("statistics") or {}
        title = _unescape(sn.get("title") or "").strip()
        if not title:
            continue
        out.append({"source": f"youtube:{region}", "title": title, "key": title,
                    "score": int(st.get("viewCount") or 0), "lang": sn.get("defaultAudioLanguage") or "",
                    "desc": sn.get("channelTitle") or "", "extract": ", ".join((sn.get("tags") or [])[:6])})
    return out


def parse_trends_rss(xml: str, geo: str) -> list[dict]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = re.search(r"<title>(.*?)</title>", block, re.S)
        traffic = re.search(r"<ht:approx_traffic>(.*?)</ht:approx_traffic>", block)
        news = re.findall(r"<ht:news_item_title>(.*?)</ht:news_item_title>", block, re.S)
        if not title:
            continue
        q = _unescape(title.group(1).strip())
        t = (traffic.group(1) if traffic else "0").replace(",", "").replace("+", "")
        out.append({"source": f"google_trends:{geo}", "title": q, "key": q, "score": int(t) if t.isdigit() else 0,
                    "lang": "en", "desc": "", "extract": " | ".join(_unescape(n.strip()) for n in news[:2])})
    return out


def _unescape(s: str) -> str:
    import html
    return html.unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S))


# ---------- safety ----------

def is_safe(it: dict) -> tuple[bool, str]:
    text = " ".join([it.get("title", ""), it.get("desc", ""), it.get("extract", "")])
    flags = topic_flags(text, mode="trend")
    if flags:
        return False, ", ".join(flags)
    if EXTRA_NEWS.search(text):
        return False, "news about violence or politics"
    return True, ""


# ---------- channels ----------

def channel_profiles() -> list[dict]:
    out = []
    for ch in channels():
        if ch.get("type") in ("clips", "kids", "brainrot"):    # podcast clips, kids and Brain Snack don't chase news
            continue
        out.append({"id": ch["id"], "market": ch.get("market"), "language": ch.get("language"),
                    "profile": f"{ch['name']}: {ch.get('niche', '')}"})
    return out


def _eligible(it: dict, market: str) -> bool:
    if market == "US":
        return it["source"] in ("wikipedia:en", "google_trends:US", "youtube:US")
    return it["source"] in ("wikipedia:hi", "wikipedia:en", "google_trends:IN", "youtube:IN")


def assign_with_brain(brain, items: list[dict], profiles: list[dict]) -> dict[str, list[dict]]:
    """One AI call: per channel, up to 3 trends that make a real on-brand video, with an angle."""
    from .policy import never_rules_text
    lines = []
    for i, it in enumerate(items):
        size = (f"{it['score']:,} views, {it['spike']:g}x usual" if it.get("spike") and it["spike"] < 99 else
                f"{it['score']:,} views, new page") if it["source"].startswith("wikipedia") else (
            f"trending YouTube video, {it['score']:,} views" if it["source"].startswith("youtube") else
            f"{it['score']:,}+ searches")
        what = it.get("desc") or it.get("extract", "")[:90]
        lines.append(f"{i}: {it['title']} - {what} - {it['source']} ({size})")
    chans = "\n".join(f"{p['id']}: {p['profile']} (market {p['market']})" for p in profiles)
    data, _ = brain.ask_json("writer", ASSIGN_PROMPT.format(items="\n".join(lines), channels=chans,
                                                            rules=never_rules_text()), temperature=0.3)
    out: dict[str, list[dict]] = {}
    valid = {p["id"]: p for p in profiles}
    for ch_id, picks in (data or {}).items():
        if ch_id not in valid or not isinstance(picks, list):
            continue
        keep = []
        for pk in picks[:3]:
            try:
                it = items[int(pk.get("i"))]
            except (TypeError, ValueError, IndexError, AttributeError):
                continue
            if _eligible(it, valid[ch_id]["market"]):
                keep.append({**it, "angle": str(pk.get("angle") or "").strip()})
        if keep:
            out[ch_id] = keep
    return out


def assign_with_embeddings(items: list[dict], profiles: list[dict], embedder=None, per_channel: int = 3) -> dict:
    """Fallback without an AI model: the closest eligible items per channel (rough; the writer still judges)."""
    import numpy as np
    if embedder is None:
        from .media.visuals import _embedder
        embedder = _embedder()
    if not items or not profiles:
        return {}
    iv = np.asarray(embedder.encode([f"{it['title']}. {it.get('desc', '')}"[:300] for it in items], is_query=True))
    pv = np.asarray(embedder.encode([p["profile"] for p in profiles]))
    sims = iv @ pv.T
    out = {}
    for j, p in enumerate(profiles):
        cands = sorted(((float(sims[i, j]), it) for i, it in enumerate(items) if _eligible(it, p["market"])),
                       key=lambda c: -c[0])
        out[p["id"]] = [{**it, "angle": ""} for _, it in cands[:per_channel]]
    return out


def hint_text(it: dict) -> str:
    src = it["source"]
    if src.startswith("wikipedia"):
        lang = "Hindi" if src.endswith(":hi") else "English"
        about = f" ({it['desc']})" if it.get("desc") else ""
        jump = f", {it['spike']:g}x its usual" if it.get("spike") and it["spike"] < 99 else ", new page"
        base = f"Trending now: {it['title']}{about}: {it['score']:,} {lang} Wikipedia views yesterday{jump}"
    elif src.startswith("youtube"):
        geo = src.split(":")[1]
        base = (f"Trending on YouTube in {'India' if geo == 'IN' else 'the US'} today: \"{it['title']}\" "
                f"({it['score']:,} views; the subject people watch now, never copy the video)")
    else:
        geo = src.split(":")[1]
        base = f"Trending search in {'India' if geo == 'IN' else 'the US'}: \"{it['title']}\" ({it['score']:,}+ searches)"
    return base + (f". Angle idea: {it['angle']}" if it.get("angle") else "")


# ---------- daily run ----------

def collect(day: date | None = None, log=print) -> dict:
    """Fetches the feeds once per day (cached in data/state/trends/), keeps real spikes, removes never-topics.
    Never raises: a broken feed just means fewer ideas."""
    day = day or (datetime.utcnow().date() - timedelta(days=1))
    STATE.mkdir(parents=True, exist_ok=True)
    cache = STATE / f"{day.isoformat()}_items.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    items, errors = [], []
    for project, n in (("en.wikipedia", 40), ("hi.wikipedia", 25)):
        try:
            items += wikipedia_top(project, day, n)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{project}: {e}")
    try:
        wikipedia_spikes(items, day)
        items = [it for it in items if not it["source"].startswith("wikipedia") or it.get("spike", 0) >= SPIKE_MIN]
        wikipedia_describe(items)
    except Exception as e:  # noqa: BLE001
        errors.append(f"wikipedia details: {e}")
    for geo in ("US", "IN"):
        try:
            items += google_trends(geo)
        except Exception as e:  # noqa: BLE001
            errors.append(f"google_trends {geo}: {e}")
        try:
            items += youtube_popular(geo)
        except Exception as e:  # noqa: BLE001
            errors.append(f"youtube_popular {geo}: {e}")
    safe, dropped = [], []
    for it in items:
        ok, why = is_safe(it)
        if ok:
            safe.append(it)
        else:
            dropped.append({"title": it["title"], "why": why})
    result = {"day": day.isoformat(), "fetched": time.strftime("%Y-%m-%d %H:%M"), "items": safe,
              "dropped": dropped, "errors": errors}
    cache.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Trends {day}: {len(safe)} safe trending items ({len(dropped)} removed by the never-topics list)")
    return result


def trend_hints(brain=None, day: date | None = None, log=print) -> dict[str, list[str]]:
    """{channel_id: ["Trending now: ... Angle idea: ...", ...]} for the week planner (cached per day)."""
    try:
        res = collect(day, log=log)
        day_s = res["day"]
        cache = STATE / f"{day_s}_channels.json"
        if cache.exists():
            by_channel = json.loads(cache.read_text(encoding="utf-8"))
        else:
            profiles = channel_profiles()
            try:
                by_channel = assign_with_brain(brain, res["items"], profiles) if brain else None
            except Exception as e:  # noqa: BLE001
                log(f"Trend matching by AI failed ({e}); using the simple match")
                by_channel = None
            if by_channel is None:
                by_channel = assign_with_embeddings(res["items"], profiles)
            cache.write_text(json.dumps(by_channel, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - trends are a bonus, never a blocker
        log(f"Trends unavailable: {e}")
        return {}
    return {ch: [hint_text(it) for it in its] for ch, its in by_channel.items() if its}
