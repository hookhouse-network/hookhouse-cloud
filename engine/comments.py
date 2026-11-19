"""Viewers' comments: answers, video ideas and a tidy comment section. The owner approves every reply.

Idea from youtube-automation-agent (MIT, "Audience Engagement Studio": comment sync, questions, reply drafts that
post only after approval, ideas from repeated requests), built our own way:
- Every evening: new comments on our videos from the last 7 days. YouTube commentThreads.list (1 unit per video,
  only videos that have comments); Instagram /{media}/comments when the token has instagram_manage_comments.
  Made-for-Kids videos have comments switched off by law, so Bloop is never touched.
- One AI pass labels them (question / idea / praise / correction / criticism / spam / abuse) and drafts a short,
  warm reply in the comment's language: no links, no promises, no personal details; never-topics are dropped.
- Telegram digest: the best few with their draft and ✅ Reply / ⏭ Skip (or /reply <n> <your words>). A reply posts
  only after that tap (YouTube comments.insert = 50 units, at most REPLY_MAX a day; Instagram /replies).
- Viewer ideas reach the weekly topic planner as hints. Comment data is deleted after 30 days (API policy)."""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

import requests

from .config import ROOT
from engine.core.http import HTTP

YT = "https://www.googleapis.com/youtube/v3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    n INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, comment_id TEXT UNIQUE, channel TEXT, video_id TEXT,
    item_id TEXT, author TEXT, text TEXT, published REAL, likes INTEGER, kind TEXT, idea TEXT, draft TEXT,
    status TEXT, fetched_at REAL, replied_at REAL, reply_id TEXT);
"""
KINDS = ("question", "idea", "praise", "correction", "criticism", "spam", "abuse", "other")
DAYS_BACK, KEEP_DAYS, FETCH_MAX, DIGEST_MAX, REPLY_MAX = 7, 30, 60, 6, 20
REPLY_CHARS = 220
SPAM = re.compile(r"(https?://|www\.|sub4sub|check (out )?my (channel|page)|whats\s*app|telegram\.me|t\.me/|"
                  r"promo|crypto|forex|bitcoin|earn \$|dm me)", re.I)

# Buying intent (owner, 16 Nov, from the income articles: "views are attention, questions are intent"): a viewer
# asking where to get a planner / PDF / template is worth more than 500 silent views. These go to the top of the
# digest and feed the product research (engine/product_research.py).
BUY = re.compile(r"(where (can|do) i (get|buy|find|download)|\bpdf\b|printable|template|spreadsheet|worksheet|"
                 r"\bdownload\b|link (please|pls|plz)|\bprice\b|how much (is|for)|\bbuy\b|kaha(n)? (milega|milegi|se)|"
                 r"link (do|bhejo|dena)|kitne ka|kitne ki)", re.I)


def buying(text: str) -> bool:
    return bool(BUY.search(text or "")) and not SPAM.search(text or "")


def buy_signals(days: int = 30, conn=None) -> list[tuple[str, str]]:
    """(channel, comment) for every buying question of the last days (comments are kept 30 days by policy)."""
    conn = conn or connect()
    rows = conn.execute("SELECT channel, text FROM comments WHERE fetched_at > ? AND kind NOT IN ('spam','abuse')",
                        (time.time() - days * 86400,)).fetchall()
    return [(ch, t) for ch, t in rows if buying(t)]


PROMPT = """You manage the comment section of the {lang} channel "{name}" ({niche}).
For each viewer comment below, return JSON:
{{"comments": [{{"n": <number>, "kind": "question|idea|praise|correction|criticism|spam|abuse|other",
  "idea": "a video topic the viewer asks for, else empty",
  "reply": "a short, warm reply (max 200 characters) in the comment's own language"}}]}}
Rules for replies: sound like a friendly human from the channel; answer questions only with facts you are sure of
(else thank them and say you'll look into it); thank corrections and say you'll check; never argue; no links,
no @mentions, no promises of dates, giveaways or money, no personal details, nothing about politics, religion
disputes, adult topics or gambling. Spam and abuse get an empty reply.

Comments:
{rows}"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or ROOT / "data" / "analytics.db")
    conn.executescript(SCHEMA)
    return conn


def _ts(iso: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def fetch_youtube(channel_id: str, video_id: str, session=HTTP) -> list[dict]:
    from .publish import add_quota, quota_ok, yt_access_token
    tok = yt_access_token(channel_id, session)
    if not tok or not quota_ok(1):
        return []
    r = session.get(f"{YT}/commentThreads", headers={"Authorization": f"Bearer {tok}"}, timeout=30,
                    params={"part": "snippet", "videoId": video_id, "maxResults": 50, "order": "time",
                            "textFormat": "plainText"})
    add_quota(1)
    if getattr(r, "status_code", 200) == 403:          # comments switched off on this video
        return []
    r.raise_for_status()
    out = []
    for th in (r.json() or {}).get("items") or []:
        top = (th.get("snippet") or {}).get("topLevelComment") or {}
        sn = top.get("snippet") or {}
        author = (sn.get("authorChannelId") or {}).get("value")
        if not top.get("id") or (author and author == sn.get("channelId")):
            continue                                      # our own comments
        out.append({"platform": "youtube", "comment_id": top["id"], "author": sn.get("authorDisplayName", ""),
                    "text": sn.get("textDisplay") or sn.get("textOriginal") or "", "likes": int(sn.get("likeCount") or 0),
                    "published": _ts(sn.get("publishedAt", ""))})
    return out


def fetch_instagram(channel_id: str, media_id: str, session=HTTP) -> list[dict]:
    from .publish import GRAPH, IG_GRAPH, meta_creds
    c = meta_creds(channel_id)
    if not c:
        return []
    host = IG_GRAPH if c.get("login") == "instagram" else GRAPH
    r = session.get(f"{host}/{media_id}/comments", timeout=30,
                    params={"fields": "id,text,username,timestamp,like_count", "access_token": c["access_token"]}).json()
    if r.get("error"):                                    # no instagram_manage_comments permission yet
        return []
    return [{"platform": "instagram", "comment_id": x["id"], "author": x.get("username", ""), "text": x.get("text", ""),
             "likes": int(x.get("like_count") or 0), "published": _ts(x.get("timestamp", ""))}
            for x in r.get("data") or [] if x.get("id")]


def store(conn, rows: list[dict], channel: str, video_id: str, item_id: str = "") -> int:
    n = 0
    for r in rows:
        cur = conn.execute("INSERT OR IGNORE INTO comments(platform, comment_id, channel, video_id, item_id, author, "
                           "text, published, likes, status, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (r["platform"], r["comment_id"], channel, video_id, item_id, r["author"][:80],
                            r["text"][:1500], r["published"], r["likes"], "new", time.time()))
        n += cur.rowcount
    conn.commit()
    return n


def safe_reply(text: str) -> str:
    """No links, no @mentions, short, nothing on the never-topics list."""
    t = re.sub(r"https?://\S+|www\.\S+", "", str(text or ""))
    t = re.sub(r"@\w+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > REPLY_CHARS:
        t = t[:REPLY_CHARS - 1].rsplit(" ", 1)[0] + "…"
    try:
        from .policy import topic_flags
        if topic_flags(t):
            return ""
    except Exception:  # noqa: BLE001
        pass
    return t


def _rules(text: str) -> str:
    if SPAM.search(text or ""):
        return "spam"
    if "?" in (text or ""):
        return "question"
    return "other"


def classify(conn, brain=None, log=print) -> int:
    """Labels new comments and drafts replies (one AI call per channel); rules only when no AI answers."""
    from .config import channel as get_channel
    rows = conn.execute("SELECT n, channel, text FROM comments WHERE status='new' ORDER BY n LIMIT 120").fetchall()
    by_ch: dict[str, list] = {}
    for n, ch, text in rows:
        by_ch.setdefault(ch, []).append((n, text))
    done = 0
    for cid, items in by_ch.items():
        labels: dict[int, dict] = {}
        if brain is not None:
            try:
                ch = get_channel(cid)
                data, _ = brain.ask_json("manager", PROMPT.format(
                    lang="Hindi" if ch.get("language") == "hi" else "English", name=ch.get("name", cid),
                    niche=ch.get("niche", ""), rows="\n".join(f"{n}. {t[:400]}" for n, t in items)), temperature=0.4)
                labels = {int(x.get("n")): x for x in data.get("comments", []) if str(x.get("n", "")).isdigit()}
            except Exception as e:  # noqa: BLE001 - the rules below still sort them
                log(f"comments: AI labelling for {cid} failed ({str(e)[:80]})")
        for n, text in items:
            lab = labels.get(n) or {}
            kind = lab.get("kind") if lab.get("kind") in KINDS else _rules(text)
            if SPAM.search(text or ""):
                kind = "spam"
            draft = "" if kind in ("spam", "abuse") else safe_reply(lab.get("reply", ""))
            idea = str(lab.get("idea") or "").strip()[:120] if kind in ("idea", "question") else ""
            worth = draft or kind in ("question", "correction", "criticism")    # you can still answer by hand
            status = "ignored" if kind in ("spam", "abuse") or not worth else "ready"
            conn.execute("UPDATE comments SET kind=?, idea=?, draft=?, status=? WHERE n=?", (kind, idea, draft, status, n))
            done += 1
    conn.commit()
    return done


def due_videos(now: float | None = None) -> list[dict]:
    from .config import channel as get_channel
    from .stats_fetch import posted_videos
    now = now or time.time()
    out = []
    for v in posted_videos():
        if now - float(v.get("posted_at") or 0) > DAYS_BACK * 86400:
            continue
        try:
            if get_channel(v["channel"]).get("type") == "kids":
                continue
        except Exception:  # noqa: BLE001
            continue
        out.append(v)
    return sorted(out, key=lambda v: float(v.get("posted_at") or 0), reverse=True)   # newest first: most comments


def digest(conn, send=None, log=print) -> int:
    """Telegram: the best ready comments with their draft reply and buttons."""
    if send is None:
        from .telegram_bot import send
    order = "CASE kind WHEN 'question' THEN 0 WHEN 'correction' THEN 1 WHEN 'idea' THEN 2 WHEN 'criticism' THEN 3 ELSE 4 END"
    rows = conn.execute(f"SELECT n, platform, channel, author, text, kind, draft FROM comments WHERE status='ready' "
                        f"ORDER BY {order}, likes DESC, n LIMIT ?", (DIGEST_MAX * 4,)).fetchall()
    rows = sorted(rows, key=lambda r: not buying(r[4]))[:DIGEST_MAX]     # buying questions first (stable sort)
    for n, plat, ch, author, text, kind, draft in rows:
        if buying(text):
            kind = "🛒 wants to buy / download"
            try:
                from .store_publish import shop_link
                got = shop_link(ch, free=True) or shop_link(ch)
            except Exception:  # noqa: BLE001
                got = None
            if got:
                kind += f"\n(our link for this channel: {got[1]}; it is already in the video description)"
        buttons = ([{"text": "✅ Reply", "callback_data": f"cr:{n}"}] if draft else []) + \
            [{"text": "⏭ Skip", "callback_data": f"cs:{n}"}]
        send(f"💬 {ch} · {plat} · {kind}\n{author}: \"{text[:300]}\"\n\n"
             + (f"Reply: {draft}\n(Or write your own: /reply {n} your words)" if draft else
                f"No draft: answer with /reply {n} your words"), reply_markup={"inline_keyboard": [buttons]})
        conn.execute("UPDATE comments SET status='asked' WHERE n=?", (n,))
    conn.commit()
    return len(rows)


def replies_today(conn, now: float | None = None) -> int:
    now = now or time.time()
    return conn.execute("SELECT COUNT(*) FROM comments WHERE replied_at > ?", (now - 86400,)).fetchone()[0]


def reply(n: int, text: str | None = None, conn=None, session=HTTP) -> str:
    """Posts the approved reply (owner's tap or /reply). Returns a line for Telegram."""
    conn = conn or connect()
    row = conn.execute("SELECT platform, comment_id, channel, draft, status FROM comments WHERE n=?", (n,)).fetchone()
    if not row:
        return "That comment is gone (older than 30 days?)."
    plat, cid_, channel, draft, status = row
    if status == "replied":
        return "Already answered ✓"
    msg = safe_reply(text if text else draft)
    if not msg:
        return "Nothing to send (the reply was empty or touched a never-topic). Write one with /reply."
    if replies_today(conn) >= REPLY_MAX:
        return f"Daily reply limit reached ({REPLY_MAX}); try again tomorrow."
    if plat == "youtube":
        from .publish import add_quota, quota_ok, yt_access_token
        tok = yt_access_token(channel, session)
        if not tok:
            return "YouTube isn't connected for this channel."
        if not quota_ok(50):
            return "YouTube's daily quota is used up; the reply waits for tomorrow."
        r = session.post(f"{YT}/comments", params={"part": "snippet"}, headers={"Authorization": f"Bearer {tok}"},
                         json={"snippet": {"parentId": cid_, "textOriginal": msg}}, timeout=30)
        add_quota(50)
        if getattr(r, "status_code", 200) >= 400:
            return f"YouTube refused the reply (HTTP {r.status_code})."
        rid = (r.json() or {}).get("id", "")
    else:
        from .publish import GRAPH, IG_GRAPH, meta_creds
        c = meta_creds(channel)
        if not c:
            return "Instagram isn't connected for this channel."
        host = IG_GRAPH if c.get("login") == "instagram" else GRAPH
        r = session.post(f"{host}/{cid_}/replies", data={"message": msg, "access_token": c["access_token"]},
                         timeout=30).json()
        if not r.get("id"):
            return "Instagram refused the reply: " + str((r.get("error") or {}).get("message") or r)[:120]
        rid = r["id"]
    conn.execute("UPDATE comments SET status='replied', replied_at=?, reply_id=?, draft=? WHERE n=?",
                 (time.time(), rid, msg, n))
    conn.commit()
    return "✅ Replied."


def skip(n: int, conn=None) -> str:
    conn = conn or connect()
    conn.execute("UPDATE comments SET status='skipped' WHERE n=?", (n,))
    conn.commit()
    return "Skipped."


def ideas(channel_id: str, k: int = 5, conn=None) -> list[str]:
    """Recent viewer requests for the weekly topic planner (most liked first)."""
    conn = conn or connect()
    rows = conn.execute("SELECT idea, likes FROM comments WHERE channel=? AND idea<>'' ORDER BY likes DESC, n DESC "
                        "LIMIT ?", (channel_id, k * 3)).fetchall()
    seen, out = set(), []
    for idea, _ in rows:
        key = idea.lower()
        if key not in seen:
            seen.add(key)
            out.append(f"Viewers asked: {idea}")
        if len(out) >= k:
            break
    return out


def purge(conn, now: float | None = None) -> int:
    now = now or time.time()
    cur = conn.execute("DELETE FROM comments WHERE fetched_at < ?", (now - KEEP_DAYS * 86400,))
    conn.commit()
    return cur.rowcount


def daily(brain=None, log=print, session=HTTP, conn=None, send=None, videos=None) -> dict:
    conn = conn or connect()
    purge(conn)
    calls = new = 0
    for v in videos if videos is not None else due_videos():
        if calls >= FETCH_MAX:
            break
        calls += 1
        try:
            rows = (fetch_youtube(v["channel"], v["id"], session) if v["platform"] == "youtube"
                    else fetch_instagram(v["channel"], v["id"], session))
        except Exception as e:  # noqa: BLE001
            log(f"comments {v['id']}: {str(e)[:100]}")
            continue
        new += store(conn, rows, v["channel"], v["id"], v.get("item", ""))
    labelled = classify(conn, brain, log) if new else 0
    sent = digest(conn, send, log)
    return {"videos": calls, "new": new, "labelled": labelled, "sent": sent}
