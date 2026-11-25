"""Daily stats fetch: views, watch time, likes, shares and subs for every video we posted (official APIs only).

Reads the upload log (data/publish_log.jsonl), then stores snapshots in data/analytics.db at 2 h, 24 h, 48 h and
7 days after posting, then once a day. The dashboard, the Telegram /channels command and the weekly learning loop
all read from there. Videos on accounts that aren't connected are skipped quietly.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from . import analytics
from .config import ROOT
from .publish import GRAPH, IG_GRAPH, LOG, SECRETS
from engine.core.http import HTTP

BUCKETS = (2, 24, 48, 168)


def posted_videos() -> list[dict]:
    """Every successful real upload: {platform, channel, id, item, title, posted_at}."""
    out = []
    if not LOG.exists():
        return out
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    deleted = {(r.get("details") or {}).get("deleted_video_id") for r in rows} - {None}   # removed after a change
    for a in rows:
        res, det = a.get("result") or {}, a.get("details") or {}
        if a.get("platform") == "youtube" and res.get("video_id") in deleted:
            continue
        if not a.get("done") or det.get("dry_run"):
            continue
        vid = res.get("video_id") if a.get("platform") == "youtube" else res.get("media_id")
        if not vid or a.get("platform") not in ("youtube", "instagram") or not str(a.get("what", "")).startswith(
                ("upload", "publish")):
            continue
        if "story" in str(a.get("what", "")).lower():    # 19 Nov: Story teasers vanish after 24 h (insights then say
            continue                                   # "object does not exist") and doubled every video in reviews
        posted = a.get("at") or time.time()
        if a.get("when"):
            try:
                posted = max(posted, datetime.fromisoformat(a["when"].replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
        out.append({"platform": a["platform"], "channel": a["channel"], "id": vid, "item": a.get("item_id") or vid,
                    "title": det.get("title", ""), "posted_at": posted,
                    "format": det.get("format") or ("short" if a["platform"] == "instagram" else None)})
    return out


def due_bucket(hours: float) -> int | None:
    """Which snapshot is due now: the latest fixed bucket passed, then one per day after a week."""
    if hours < BUCKETS[0]:
        return None
    if hours >= 192:
        return int(hours // 24) * 24
    return max(b for b in BUCKETS if b <= hours)


ANALYTICS_READY_H = 72                   # YouTube Analytics fills in 2-3 days after a video goes public


def _youtube(v: dict, session) -> dict | None:
    """Early buckets (< 3 days): the public counters (minutes old, 1 quota unit). After that the Analytics report
    (watch %, engaged views, shares, subs). None = nothing reliable yet: try again on the next run."""
    hours = (time.time() - v["posted_at"]) / 3600
    if hours < ANALYTICS_READY_H:
        return _youtube_public(v, session)
    from .connect import fetch_youtube_metrics
    start = datetime.fromtimestamp(v["posted_at"], timezone.utc).strftime("%Y-%m-%d")
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    m = fetch_youtube_metrics(v["channel"], v["id"], start, end, session=session)
    if m is None:
        return None
    if not m:                                          # Analytics not filled in yet: public counters instead
        return _youtube_public(v, session)
    return {"views": m.get("views"), "engaged_views": m.get("engagedViews"),
            "avg_pct_viewed": m.get("averageViewPercentage"), "avg_view_s": m.get("averageViewDuration"),
            "likes": m.get("likes"), "comments": m.get("comments"), "shares": m.get("shares"),
            "subs_gained": m.get("subscribersGained")}


def _youtube_public(v: dict, session) -> dict | None:
    import os
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        return None
    r = session.get("https://www.googleapis.com/youtube/v3/videos", timeout=30,
                    params={"part": "statistics", "id": v["id"], "key": key})
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        return None                                    # private / scheduled / removed
    st = items[0].get("statistics") or {}
    return {"views": int(st.get("viewCount") or 0), "likes": int(st.get("likeCount") or 0),
            "comments": int(st.get("commentCount") or 0)}


def _instagram(v: dict, session) -> dict | None:
    p = SECRETS / f"meta_{v['channel']}.json"
    if not p.exists():
        return None
    from .links import hold_note                       # 25 Nov: Brain Snack's account is hidden behind Instagram's
    if hold_note(v["channel"], "instagram"):           # human check; every stats run raised a HIGH heal item
        return None                                    # ("object does not exist"): a held account is not asked
    rec = json.loads(p.read_text(encoding="utf-8"))
    token, host = rec.get("access_token"), (IG_GRAPH if rec.get("login") == "instagram" else GRAPH)
    r = session.get(f"{host}/{v['id']}/insights", params={
        "metric": "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time", "access_token": token},
        timeout=30)
    if getattr(r, "status_code", 200) >= 400:
        # 18 Nov: "400 Bad Request" hid Meta's reason ("(#10) Application does not have permission": the token was
        # made without instagram_manage_insights). The reason goes to the heal queue, which tells the owner.
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        err = f"Instagram insights HTTP {r.status_code}: {msg}"
        try:
            from . import heal
            heal.report("stats:instagram", err, channel=v.get("channel"), platform="instagram")
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(err)
    try:                                               # 19 Nov: insights answer again -> the old errors close
        from . import heal
        heal.resolve("stats:instagram: ")
    except Exception:  # noqa: BLE001
        pass
    vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in r.json().get("data", [])}
    avg_ms = vals.get("ig_reels_avg_watch_time")
    return {"views": vals.get("views"), "likes": vals.get("likes"), "comments": vals.get("comments"),
            "shares": vals.get("shares"), "saves": vals.get("saved"),
            "avg_view_s": round(avg_ms / 1000, 1) if avg_ms else None}


def fetch(session=HTTP, log=print, conn=None) -> int:
    conn = conn or analytics.connect()
    # repair (18 Nov): Analytics answered "no rows yet" with zeros, which were saved as real snapshots and never
    # fetched again. Their signature: watch % exactly 0 (public counters leave it empty), taken within 3 days.
    conn.execute("DELETE FROM video_metrics WHERE platform='youtube' AND COALESCE(views,0)=0 AND avg_pct_viewed=0 "
                 "AND fetched_at - posted_at < ?", (ANALYTICS_READY_H * 3600,))
    conn.commit()
    done = 0
    for v in posted_videos():
        hours = (time.time() - v["posted_at"]) / 3600
        b = due_bucket(hours)
        if b is None:
            continue
        if conn.execute("SELECT 1 FROM video_metrics WHERE item_id=? AND platform=? AND hours_after=?",
                        (v["item"], v["platform"], b)).fetchone():
            continue
        try:
            m = (_youtube if v["platform"] == "youtube" else _instagram)(v, session)
        except Exception as e:  # noqa: BLE001 - one failed video must not stop the rest
            log(f"  {v['platform']} {v['id']}: {e}")
            continue
        if m is None:
            continue
        if m.get("engaged_views") is not None and m.get("views") and m.get("stayed_pct") is None:
            # 19 Nov (owner: "more than 50% just swipe"): engaged views / views = Studio's "viewed" share (the rest
            # swiped away). It was fetched but never stored, so no review could see the swipe problem.
            m["stayed_pct"] = round(100.0 * float(m["engaged_views"]) / float(m["views"]), 1)
        analytics.record(conn, item_id=v["item"], channel=v["channel"], platform=v["platform"], video_id=v["id"],
                         hook=v["title"], posted_at=v["posted_at"], hours_after=b, format=v.get("format"), **m)
        done += 1
    log(f"Stats: {done} new snapshots saved")
    channel_stats(session, log)
    try:                                               # 19 Nov: scripts + their numbers -> our own training set
        from .training_data import build
        log(f"Training set: {build()} labelled videos")
    except Exception as e:  # noqa: BLE001 - stats are saved either way
        log(f"training set: {e}")
    return done


TERMS = ROOT / "data" / "state" / "search_terms.json"


def search_terms(session=HTTP, log=print, days: int = 28) -> dict:
    """Weekly, per connected channel: the YouTube searches that brought views (our own channel's data, YouTube
    Analytics insightTrafficSourceDetail for YT_SEARCH). Kept 12 weeks. Drift alert (idea from claude-seo's
    seo-drift): search views down 30%+ on last week. The terms also go to the planner as topic hints."""
    from datetime import date, timedelta
    from .publish import yt_access_token
    state = json.loads(TERMS.read_text(encoding="utf-8")) if TERMS.exists() else {}
    end = date.today()
    start = end - timedelta(days=days)
    week = f"{end.isocalendar()[0]}-W{end.isocalendar()[1]}"
    alerts = []
    for p in sorted(SECRETS.glob("youtube_*.json")) if SECRETS.exists() else []:
        cid = p.stem.replace("youtube_", "", 1)
        try:
            tok = yt_access_token(cid, session)
            if not tok:
                continue
            r = session.get("https://youtubeanalytics.googleapis.com/v2/reports",
                            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
                            params={"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
                                    "metrics": "views", "dimensions": "insightTrafficSourceDetail",
                                    "filters": "insightTrafficSourceType==YT_SEARCH", "sort": "-views",
                                    "maxResults": 25})
            r.raise_for_status()
            rows = [[str(t), int(v or 0)] for t, v in (r.json().get("rows") or [])]
        except Exception as e:  # noqa: BLE001
            log(f"  search terms {cid}: {e}")
            continue
        hist = state.setdefault(cid, {}).setdefault("history", [])
        total = sum(v for _, v in rows)
        hist[:] = [h for h in hist if h.get("week") != week] + [{"week": week, "total": total, "terms": rows}]
        hist[:] = hist[-12:]
        if len(hist) >= 2 and hist[-2]["total"] >= 200 and total < 0.7 * hist[-2]["total"]:
            alerts.append(f"{cid}: YouTube search views {hist[-2]['total']:,} -> {total:,} (28 days)")
    TERMS.parent.mkdir(parents=True, exist_ok=True)
    TERMS.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"alerts": alerts, "channels": {c: (v.get("history") or [{}])[-1].get("terms", []) for c, v in state.items()}}


def top_terms(channel_id: str, n: int = 8) -> list[tuple[str, int]]:
    if not TERMS.exists():
        return []
    hist = (json.loads(TERMS.read_text(encoding="utf-8")).get(channel_id) or {}).get("history") or []
    return [tuple(x) for x in (hist[-1]["terms"] if hist else [])][:n]


def channel_stats(session=HTTP, log=print) -> int:
    """Subscribers / followers per connected account (YouTube Data API, Instagram Graph API) -> account_stats."""
    from . import db
    from .config import channels
    from .publish import yt_access_token
    conn, n = db.connect(), 0
    for ch in channels():
        cid = ch["id"]
        try:
            token = yt_access_token(cid, session) if (SECRETS / f"youtube_{cid}.json").exists() else None
            if token:
                r = session.get("https://www.googleapis.com/youtube/v3/channels", params={
                    "part": "statistics", "mine": "true"}, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                r.raise_for_status()
                st = ((r.json().get("items") or [{}])[0]).get("statistics") or {}
                old = db.get_account_stats(conn, cid, "youtube") or {}
                db.save_account_stats(conn, cid, "youtube", old.get("us_pct"), old.get("tier1_pct"),
                                      int(st.get("subscriberCount") or 0))
                n += 1
            meta = SECRETS / f"meta_{cid}.json"
            if meta.exists():
                j = json.loads(meta.read_text(encoding="utf-8"))
                host = IG_GRAPH if j.get("login") == "instagram" else GRAPH
                r = session.get(f"{host}/{j['ig_user_id']}", params={"fields": "followers_count",
                                                                       "access_token": j["access_token"]}, timeout=30)
                r.raise_for_status()
                old = db.get_account_stats(conn, cid, "instagram") or {}
                db.save_account_stats(conn, cid, "instagram", old.get("us_pct"), old.get("tier1_pct"),
                                      int(r.json().get("followers_count") or 0))
                n += 1
        except Exception as e:  # noqa: BLE001
            from .cloud.runner import redact
            log(f"  followers {cid}: {redact(e)}")                # the URL in the error holds the token
    return n


# ---------------- live numbers (owner 17 Nov: "the dashboard has no correct views or subscribers") ----------------
# YouTube Analytics lags 2-3 days, so new videos showed nothing. The public counters (videos.list / channels.list
# statistics) update within minutes and cost 1 quota unit per 50 videos; refreshed on every cloud run.
LIVE = ROOT / "data" / "state" / "live_stats.json"


def live_stats() -> dict:
    try:
        return json.loads(LIVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"videos": {}, "channels": {}, "history": {}}


def live(session=HTTP, log=print) -> dict:
    """{'videos': {id: {views, likes, comments, title, channel, at}}, 'channels': {cid: {subs, views, videos,
    followers_ig}}, 'history': {cid: [[day, subs, views]...]}} -> data/state/live_stats.json."""
    import os
    from .config import channels
    from .publish import yt_access_token
    out = live_stats()
    key = os.environ.get("YOUTUBE_API_KEY")
    vids = [v for v in posted_videos() if v["platform"] == "youtube"]
    if key and vids:
        for k in range(0, len(vids), 50):
            chunk = vids[k:k + 50]
            try:
                r = session.get("https://www.googleapis.com/youtube/v3/videos", timeout=30, params={
                    "part": "statistics,snippet", "id": ",".join(v["id"] for v in chunk), "key": key})
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001
                from .cloud.runner import redact
                log(f"  live video stats: {redact(e)}")
                break
            found = {it["id"]: it for it in r.json().get("items", [])}
            for v in chunk:
                it = found.get(v["id"])
                if not it:
                    continue
                st = it.get("statistics") or {}
                out["videos"][v["id"]] = {"channel": v["channel"], "item": v["item"], "format": v.get("format"),
                                          "title": (it.get("snippet") or {}).get("title") or v.get("title", ""),
                                          "posted_at": v["posted_at"], "views": int(st.get("viewCount") or 0),
                                          "likes": int(st.get("likeCount") or 0),
                                          "comments": int(st.get("commentCount") or 0), "at": time.time()}
    today = time.strftime("%Y-%m-%d")

    def save(cid: str, it: dict) -> None:
        st = it.get("statistics") or {}
        rec = out["channels"].setdefault(cid, {})
        rec.update({"subs": int(st.get("subscriberCount") or 0), "views": int(st.get("viewCount") or 0),
                    "videos": int(st.get("videoCount") or 0), "yt_id": it.get("id"), "at": time.time()})
        hist = out["history"].setdefault(cid, [])
        row = [today, rec["subs"], rec["views"]]
        if hist and hist[-1][0] == today:
            hist[-1] = row
        else:
            hist.append(row)
        del hist[:-90]

    connected = [ch["id"] for ch in channels() if (SECRETS / f"youtube_{ch['id']}.json").exists()]
    known = {cid: out["channels"].get(cid, {}).get("yt_id") for cid in connected}
    if key and any(known.values()):                # one public call for every channel we know the id of
        try:
            ids = {v: k for k, v in known.items() if v}
            r = session.get("https://www.googleapis.com/youtube/v3/channels", timeout=30, params={
                "part": "statistics", "id": ",".join(ids), "key": key})
            r.raise_for_status()
            for it in r.json().get("items", []):
                save(ids[it["id"]], it)
        except Exception as e:  # noqa: BLE001
            from .cloud.runner import redact
            log(f"  live channels: {redact(e)}")
    for cid in [c for c in connected if not known.get(c)]:   # first time: the channel's id via its own login
        try:
            token = yt_access_token(cid, session)
            r = session.get("https://www.googleapis.com/youtube/v3/channels", timeout=30, headers={
                "Authorization": f"Bearer {token}"}, params={"part": "statistics", "mine": "true"})
            r.raise_for_status()
            save(cid, (r.json().get("items") or [{}])[0])
        except Exception as e:  # noqa: BLE001 - one channel must not stop the rest
            from .cloud.runner import redact
            log(f"  live channel {cid}: {redact(e)}")
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    LIVE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log(f"live stats: {len(out['videos'])} videos, {len(out['channels'])} channels")
    return out
