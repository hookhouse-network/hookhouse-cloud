"""End-of-day review (owner, 18 Nov 2026: "at each end of the day the system must review all the analytics data of
our channels and platforms: what is good, bad, what people think, where they left our videos, weak points ...
stored in our cloud folders, arranged by platform then channel/account").

Runs once a day in the evening cloud run (after the comments step). For every channel and platform:
- numbers: videos posted, views, engaged views, average % viewed, like/comment/share rates, subscribers gained,
  each video against the channel's OWN median (YouTube publishes no benchmarks; research note 10 Nov)
- good: the videos that beat the median and what they had in common (topic, hook, length, slot, music)
- bad / weak points: not shown at all after a day, viewers leaving early (retention lesson: where and on which
  line), low likes or shares for the views, failed or held uploads
- what viewers said: the day's comments by kind (questions, ideas, praise, corrections, criticism)
- lessons: one AI pass per active channel turns the numbers into "keep" / "change" rules and next-topic ideas;
  they go into our memory (playbook) so the next scripts use them, and into insights.json for the planner
Saved to data/reviews/<platform>/<channel>/<YYYY-MM-DD>.md + .json, insights.json per channel and
data/reviews/latest.md (the whole day). data/reviews is part of the encrypted cloud memory bundle.
System problems go to the heal queue; repeated weak points become "improve" items there.

Research basis: YouTube Shorts: viewed-vs-swiped-away is the first test, engaged views count for pay (Mar 2025);
Instagram: watch time, likes per reach and sends per reach (Mosseri, Jan 2025), originality push (2026).
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from datetime import datetime, timedelta

from .config import ROOT

REVIEWS = ROOT / "data" / "reviews"
LOOKBACK_D = 7                   # each review looks at the last week (one day is too few videos to learn from)
NOT_SHOWN_H = 24                 # public this long with 0 views -> the platform isn't showing it at all
BENCH = {"avg_pct_short": 70.0, "avg_pct_long": 40.0, "like_rate": 0.02, "comment_rate": 0.002}
PLATFORMS = ("youtube", "instagram", "facebook", "dailymotion", "threads", "telegram")

LESSON_PROMPT = """You are the growth analyst of the {lang} {market} channel "{name}" ({niche}).
Here are the channel's videos of the last {days} days with their real numbers (each against the channel median),
the retention lessons (where viewers left), and what viewers wrote:

{facts}

Write what the next videos must keep and change. Be concrete (hook wording, first-second visual, length, pacing,
topic type, music mood, posting slot, title/thumbnail packaging). Use only what these numbers show; when there are
too few videos say so and give the safest research-based advice for this niche.
Answer JSON only:
{{"verdict": "one sentence on how the channel is doing",
  "keep": ["up to 3 rules to keep"], "change": ["up to 3 rules to change"],
  "next_topics": ["up to 4 topic ideas that fit what worked and what viewers asked"],
  "hooks": ["up to 3 opening lines in the channel's language"],
  "music": "the music mood that fits the winners (e.g. mystery, upbeat, emotional, calm, epic, lofi, playful)"}}"""


# ---------------- data ----------------
def _plan_items(days: int) -> dict[str, dict]:
    try:
        from . import autopilot
        return {it["id"]: it for _, it in autopilot.items(days, 1)}
    except Exception:  # noqa: BLE001
        return {}


def _latest_metrics(conn, since: float) -> dict[tuple[str, str], dict]:
    """(item, platform) -> its newest snapshot."""
    rows = conn.execute("SELECT * FROM video_metrics WHERE posted_at>? ORDER BY hours_after", (since,))
    cols = [d[0] for d in rows.description]
    out: dict[tuple[str, str], dict] = {}
    for r in rows.fetchall():
        m = dict(zip(cols, r))
        out[(m["item_id"], m["platform"])] = m
    return out


def collect(now: float | None = None, days: int = LOOKBACK_D) -> dict[tuple[str, str], list[dict]]:
    """(platform, channel) -> videos of the last `days`, each with numbers + what we know about how it was made."""
    from . import analytics, stats_fetch
    now = now or time.time()
    since = now - days * 86400
    items = _plan_items(days + 1)
    metrics = _latest_metrics(analytics.connect(), since)
    live = stats_fetch.live_stats().get("videos", {})
    out: dict[tuple[str, str], list[dict]] = {}
    for v in stats_fetch.posted_videos():
        if v["posted_at"] < since or v["posted_at"] > now:
            continue
        m = dict(metrics.get((v["item"], v["platform"])) or {})
        lv = live.get(v["id"]) if v["platform"] == "youtube" else None
        if lv and (lv.get("views") or 0) >= (m.get("views") or 0):      # public counters are fresher
            m.update(views=lv["views"], likes=lv.get("likes"), comments=lv.get("comments"))
        it = items.get(v["item"]) or {}
        out.setdefault((v["platform"], v["channel"]), []).append({
            "id": v["id"], "item": v["item"], "title": (lv or {}).get("title") or v.get("title") or it.get("topic", ""),
            "topic": it.get("topic", ""), "kind": it.get("kind") or v.get("format") or "short",
            "hours": round((now - v["posted_at"]) / 3600, 1),
            "slot": datetime.fromtimestamp(v["posted_at"]).strftime("%H:%M"),
            "music": it.get("music_mood", ""), "seconds": it.get("duration_s"),
            **{k: m.get(k) for k in ("views", "engaged_views", "avg_pct_viewed", "avg_view_s", "likes", "comments",
                                     "shares", "saves", "subs_gained")}})
    return out


def _comments(channel: str, since: float) -> dict:
    try:
        from .comments import connect
        rows = connect().execute("SELECT kind, text, likes FROM comments WHERE channel=? AND published>? "
                                 "AND kind NOT IN ('spam','abuse') ORDER BY likes DESC", (channel, since)).fetchall()
    except Exception:  # noqa: BLE001
        return {"counts": {}, "quotes": []}
    return {"counts": dict(Counter(k for k, _, _ in rows)),
            "quotes": [f"[{k}] {t[:140]}" for k, t, _ in rows if k in ("criticism", "correction", "idea", "question",
                                                                          "praise")][:6]}


def _retention(channel: str, since: float) -> list[str]:
    try:
        from .retention import connect
        rows = connect().execute("SELECT lesson FROM retention WHERE channel=? AND fetched_at>? AND lesson<>''",
                                 (channel, since)).fetchall()
        return [r[0] for r in rows][:5]
    except Exception:  # noqa: BLE001
        return []


def _failures(channel: str, platform: str, since: float) -> list[str]:
    from .publish import LOG
    out = []
    if not LOG.exists():
        return out
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(line)
        except ValueError:
            continue
        if (a.get("channel") == channel and a.get("platform") == platform and float(a.get("at") or 0) >= since
                and not a.get("done") and not (a.get("details") or {}).get("dry_run")):
            err = (a.get("result") or {}).get("error")
            if err:
                out.append(str(err)[:160])
    return out


# ---------------- judging ----------------
def judge(videos: list[dict]) -> dict:
    """Rule-based good / bad / weak points from the numbers alone (works with no AI)."""
    views = [v["views"] for v in videos if v.get("views") is not None and v["hours"] >= NOT_SHOWN_H]
    med = statistics.median(views) if views else None
    good, bad, weak = [], [], []
    for v in videos:
        vw = v.get("views")
        v["vs_median"] = round(vw / med, 2) if (med and vw is not None) else None
        tag = f"'{v['title'][:60]}' ({v['kind']}, {v['slot']})"
        if vw is not None and vw == 0 and v["hours"] >= NOT_SHOWN_H:
            bad.append(f"{tag}: 0 views after {v['hours']:.0f} h: the platform isn't showing it (first frame / title "
                       "/ a new account still in its test phase)")
            continue
        if v["vs_median"] is not None and len(views) >= 3:
            if v["vs_median"] >= 1.5:
                good.append(f"{tag}: {vw} views, {v['vs_median']}x the channel median")
            elif v["vs_median"] <= 0.5:
                bad.append(f"{tag}: {vw} views, only {v['vs_median']}x the median")
        bench = BENCH["avg_pct_long" if v["kind"] == "long" else "avg_pct_short"]
        if v.get("avg_pct_viewed") and v["avg_pct_viewed"] < bench:
            weak.append(f"{tag}: viewers watched {v['avg_pct_viewed']:.0f}% on average (target {bench:.0f}%): "
                        "the start or the middle loses them")
        if vw and vw >= 100:
            if (v.get("likes") or 0) / vw < BENCH["like_rate"]:
                weak.append(f"{tag}: few likes for the views ({(v.get('likes') or 0) / vw:.1%}, target 2%+): "
                            "weak payoff or no reason to react")
            if v.get("shares") is not None and v["shares"] == 0:
                # 22 Nov: never "add a 'send this to' line": Instagram does not recommend posts that ask for shares
                weak.append(f"{tag}: nobody shared it: add a moment worth sending (a surprising true detail or a "
                            f"relatable laugh) without asking for shares")
    return {"median_views": med, "good": good, "bad": bad, "weak": weak}


def ai_lessons(brain, ch: dict, videos: list[dict], said: dict, retention: list[str]) -> dict:
    facts = [json.dumps({k: v.get(k) for k in ("title", "kind", "slot", "seconds", "music", "views", "vs_median",
                                                "engaged_views", "avg_pct_viewed", "likes", "comments", "shares",
                                                "subs_gained", "hours")}, ensure_ascii=False) for v in videos[:20]]
    if retention:
        facts.append("Retention lessons: " + " | ".join(retention))
    if said.get("quotes"):
        facts.append("Viewers wrote: " + " | ".join(said["quotes"]))
    data, _ = brain.ask_json("manager", LESSON_PROMPT.format(
        lang="Hindi" if ch.get("language") == "hi" else "English", market=ch.get("market", ""), name=ch["name"],
        niche=ch.get("niche", ""), days=LOOKBACK_D, facts="\n".join(facts)), temperature=0.3)
    return data if isinstance(data, dict) else {}


# ---------------- writing ----------------
def _md(ch_name: str, platform: str, day: str, rep: dict) -> str:
    L = [f"# {ch_name} on {platform}: review {day}", ""]
    s = rep["stats"]
    L.append(f"Videos (last {LOOKBACK_D} days): {s['videos']} | views {s['views']} | median {s['median_views']} | "
             f"subs gained {s['subs_gained']} | failed uploads {len(rep['failures'])}")
    for title, key in (("Good", "good"), ("Bad", "bad"), ("Weak points", "weak"), ("Viewers said", "said"),
                       ("Retention", "retention"), ("Failed uploads", "failures")):
        rows = rep[key]["quotes"] if key == "said" else rep[key]
        if rows:
            L += ["", f"## {title}"] + [f"- {r}" for r in rows]
    les = rep.get("lessons") or {}
    if les:
        L += ["", "## Lessons", f"{les.get('verdict', '')}"]
        for k in ("keep", "change", "next_topics", "hooks"):
            if les.get(k):
                L.append(f"- **{k}**: " + " | ".join(map(str, les[k])))
        if les.get("music"):
            L.append(f"- **music**: {les['music']}")
    L += ["", "## Videos", "| title | kind | slot | views | x median | avg % | likes | shares |", "|---|---|---|---|---|---|---|---|"]
    for v in rep["videos"]:
        L.append(f"| {v['title'][:50]} | {v['kind']} | {v['slot']} | {v.get('views')} | {v.get('vs_median')} | "
                 f"{v.get('avg_pct_viewed')} | {v.get('likes')} | {v.get('shares')} |")
    return "\n".join(L) + "\n"


def insights(channel: str) -> dict:
    """The newest lessons for one channel, merged across platforms (for the planner and the writer)."""
    out: dict = {"keep": [], "change": [], "next_topics": [], "hooks": [], "music": ""}
    for p in sorted(REVIEWS.glob(f"*/{channel}/insights.json")):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k in ("keep", "change", "next_topics", "hooks"):
            out[k] += [x for x in j.get(k, []) if x not in out[k]]
        out["music"] = out["music"] or j.get("music", "")
    return out


def planner_hints(channel: str) -> list[str]:
    i = insights(channel)
    return ([f"From our own numbers (keep): {x}" for x in i["keep"][:2]] +
            [f"From our own numbers (change): {x}" for x in i["change"][:2]] +
            [f"Topic idea from what worked: {x}" for x in i["next_topics"][:3]])


def run(brain=None, memory=None, log=print, now: float | None = None, send=None, ai: bool = True) -> dict:
    from . import heal
    from .config import channels
    now = now or time.time()
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    since = now - LOOKBACK_D * 86400
    data = collect(now)
    chans = {c["id"]: c for c in channels()}
    summary, reports = [], {}
    for (platform, cid), videos in sorted(data.items()):
        ch = chans.get(cid, {"id": cid, "name": cid})
        rep = judge(videos)
        rep.update(videos=videos, said=_comments(cid, since), retention=_retention(cid, since),
                   failures=_failures(cid, platform, now - 86400),
                   stats={"videos": len(videos), "views": sum(v.get("views") or 0 for v in videos),
                          "median_views": rep["median_views"],
                          "subs_gained": sum(v.get("subs_gained") or 0 for v in videos)})
        if ai and brain is not None and videos:
            try:
                rep["lessons"] = ai_lessons(brain, ch, videos, rep["said"], rep["retention"])
            except Exception as e:  # noqa: BLE001 - the review is saved without lessons
                log(f"review {cid}: lessons: {e}")
        folder = REVIEWS / platform / cid
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{day}.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        (folder / f"{day}.md").write_text(_md(ch["name"], platform, day, rep), encoding="utf-8")
        les = rep.get("lessons") or {}
        if les:
            (folder / "insights.json").write_text(json.dumps({**les, "day": day}, indent=1, ensure_ascii=False),
                                                  encoding="utf-8")
            if memory is not None:
                for k in ("keep", "change"):
                    for rule in les.get(k, [])[:3]:
                        text = f"{k.upper()}: {rule}"
                        hits = memory.search(text, kind="playbook", channel=cid, k=1, include_global=False)
                        if not (hits and hits[0].similarity >= 0.92):          # no near-duplicate rules
                            memory.add("playbook", text, channel=cid,
                                       meta={"source": "daily_review", "day": day, "platform": platform})
        not_shown = [b for b in rep["bad"] if "0 views" in b]
        if len(not_shown) >= 3:
            heal.improve(f"not_shown:{platform}:{cid}", "reach", f"{ch['name']} on {platform}: {len(not_shown)} "
                         f"videos got 0 views after a day", "Check the account status (restricted? made-for-kids? "
                         "new-account test), first frame and title of these videos.", evidence="; ".join(not_shown[:3]),
                         channel=cid, platform=platform)
        if len(rep["weak"]) >= 4:
            heal.improve(f"weak:{platform}:{cid}", "content", f"{ch['name']} on {platform}: {len(rep['weak'])} weak "
                         "points this week", "Rework this channel's hook/pacing template using the review's "
                         "lessons.", evidence="; ".join(rep["weak"][:3]), channel=cid, platform=platform)
        reports[(platform, cid)] = rep
        s = rep["stats"]
        summary.append(f"{ch['name']} ({platform}): {s['videos']} videos, {s['views']} views"
                       + (f", {len(rep['good'])} good, {len(rep['bad'])} weak" if (rep['good'] or rep['bad']) else "")
                       + (f", {len(rep['failures'])} failed uploads" if rep["failures"] else ""))
    heal.from_publish_log(now - 86400)
    scorecard_text = ""
    try:                                   # S6 (owner 21 Nov): one measured change per channel per day, or a reason
        from . import scorecard
        scorecard_text = scorecard.summary(scorecard.run_all(sorted(chans), now=now, log=log))
    except Exception as e:  # noqa: BLE001 - the review still goes out (said, never silent)
        log(f"daily review: scorecard failed ({type(e).__name__}: {e})")
    REVIEWS.mkdir(parents=True, exist_ok=True)
    whole = [f"# Daily review {day}", ""] + [f"- {s}" for s in summary] + [""]
    for (platform, cid), rep in reports.items():
        whole.append(_md(chans.get(cid, {"name": cid})["name"], platform, day, rep))
    (REVIEWS / "latest.md").write_text("\n".join(whole), encoding="utf-8")
    _prune()
    if send is None:
        from .telegram_bot import notify as send
    tops = [f"• {s}" for s in summary[:14]] or ["• No public videos in the last week yet."]
    imp = heal.open_items("improve")
    hi = heal.open_items("high")
    send("📊 End-of-day review\n" + "\n".join(tops) + (f"\n\n{scorecard_text}" if scorecard_text else "") +
         (f"\n\n🛠 {len(hi)} code fix(es) waiting: tell Claude 'Heal and Improve the system'" if hi else "") +
         (f"\n💡 {len(imp)} improvement(s) queued for the next 'Heal and Improve'" if imp else "") +
         "\nFull reports: data/reviews (cloud memory) and /review in Telegram.")
    log(f"daily review: {len(reports)} channel/platform reports")
    return {"day": day, "reports": len(reports), "summary": summary}


def _prune(keep_days: int = 60) -> None:
    """Old daily files go; insights.json stays. (YouTube API data: kept 30 days for other creators' data only;
    our own channel's data has no such limit, but the memory bundle must stay small.)"""
    cut = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for p in REVIEWS.glob("*/*/20??-??-??.*"):
        if p.stem < cut:
            p.unlink(missing_ok=True)


def telegram_text(channel: str | None = None) -> str:
    """/review [channel]: the newest review, short enough for one message."""
    p = REVIEWS / "latest.md"
    if not p.exists():
        return "No review yet: the first one runs this evening."
    text = p.read_text(encoding="utf-8")
    if channel:
        parts = [s for s in text.split("\n# ") if channel.lower().replace("_", " ") in s.lower()[:80]]
        text = "\n# ".join(parts) if parts else f"No review for '{channel}' yet."
    return text[:3900]
