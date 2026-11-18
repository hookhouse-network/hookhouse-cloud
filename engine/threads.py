"""Threads posting with the official Threads API (free).

Threads only takes a video from a public link. After our Reel is published, Instagram's Graph API gives the Reel's
own video link (media_url), so that link is handed to Threads: no extra hosting, no card. Each channel's Threads
profile is its Instagram account (log in to Threads with it once), added as a Threads tester of our own Meta app.

Research 13 Nov 2026 (developers.facebook.com/documentation/threads): container (media_type=VIDEO, video_url, text)
-> wait until FINISHED -> threads_publish; 250 posts per profile per 24 h; text up to 500 characters; codes from the
sign-in window are valid 1 hour; long-lived tokens last 60 days and can be refreshed once they are a day old.
Threads does not accept localhost redirect links, so the sign-in returns to an https page and the setup assistant
reads the code from the address bar."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import requests

from .config import ROOT

GRAPH = "https://graph.threads.net"
VERSION = "v1.0"
AUTHORIZE = "https://threads.net/oauth/authorize"
SCOPES = "threads_basic,threads_content_publish"
SECRETS = ROOT / "data" / "secrets"
DEFAULT_REDIRECT = "https://www.facebook.com/connect/login_success.html"
TEXT_MAX = 500
DAILY_GUARD = 200            # Threads allows 250 API posts per profile per 24 h
REFRESH_BEFORE_DAYS = 15


def token_path(channel_id: str) -> Path:
    return SECRETS / f"threads_{channel_id}.json"


def creds(channel_id: str) -> dict | None:
    p = token_path(channel_id)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return rec if rec.get("access_token") and rec.get("user_id") else None


def redirect_uri() -> str:
    return (os.environ.get("THREADS_REDIRECT_URI") or "").strip() or DEFAULT_REDIRECT


def auth_url(state: str = "hookhouse") -> str:
    q = {"client_id": os.environ.get("THREADS_APP_ID", "").strip(), "redirect_uri": redirect_uri(),
         "scope": SCOPES, "response_type": "code", "state": state}
    return AUTHORIZE + "?" + urllib.parse.urlencode(q)


def code_from_url(url: str) -> str | None:
    """The sign-in code from the address the sign-in window returned to ('#_' at the end is not part of it)."""
    if not url or "code=" not in url:
        return None
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url.split("#")[0]).query)
    code = (q.get("code") or [""])[0].strip()
    return code or None


def is_return_page(url: str) -> bool:
    base = redirect_uri().split("?")[0].rstrip("/")
    return bool(url) and url.split("?")[0].split("#")[0].rstrip("/") == base and "code=" in url


def _channel_for(username: str, hint: str | None = None) -> str | None:
    from .config import channels
    u = (username or "").lower().lstrip("@")
    for ch in channels():
        hs = ch.get("handles") or {}
        if u and u in {str(hs.get(k) or "").lower().lstrip("@") for k in ("instagram", "instagram_backup")}:
            return ch["id"]
    return hint


def connect(code: str, channel_hint: str | None = None, session=requests) -> str:
    """Code -> short token -> 60-day token, saved for the channel whose Instagram name matches."""
    app_id, secret = os.environ.get("THREADS_APP_ID", "").strip(), os.environ.get("THREADS_APP_SECRET", "").strip()
    if not (app_id and secret):
        return "Add the Threads app ID and secret first (Threads step 1)."
    r = session.post(f"{GRAPH}/oauth/access_token", data={"client_id": app_id, "client_secret": secret,
                                                          "grant_type": "authorization_code",
                                                          "redirect_uri": redirect_uri(), "code": code}, timeout=30)
    short = r.json() if r is not None else {}
    if not short.get("access_token"):
        return "Threads refused the sign-in code: " + str(short.get("error_message") or short.get("error") or short)[:160]
    ll = session.get(f"{GRAPH}/access_token", params={"grant_type": "th_exchange_token", "client_secret": secret,
                                                      "access_token": short["access_token"]}, timeout=30).json()
    token = ll.get("access_token") or short["access_token"]
    expires = time.time() + float(ll.get("expires_in") or 3600)
    me = session.get(f"{GRAPH}/{VERSION}/me", params={"fields": "id,username", "access_token": token}, timeout=30).json()
    uid = str(me.get("id") or short.get("user_id") or "")
    username = me.get("username") or ""
    cid = _channel_for(username, channel_hint)
    if not (uid and cid):
        return f"Connected @{username or '?'}, but it isn't any channel's Instagram name; open this channel's step and try again."
    SECRETS.mkdir(parents=True, exist_ok=True)
    token_path(cid).write_text(json.dumps({"user_id": uid, "username": username, "access_token": token,
                                           "expires_at": expires, "saved_at": time.time()}, indent=1),
                               encoding="utf-8")
    return f"✅ Threads @{username} connected to {cid} (60-day login, renewed automatically)."


def refresh_all(session=requests, log=print, now: float | None = None) -> int:
    """Renews 60-day tokens that are at least a day old and run out within 15 days."""
    now = now or time.time()
    n = 0
    for p in sorted(SECRETS.glob("threads_*.json")) if SECRETS.exists() else []:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        left = (rec.get("expires_at") or 0) - now
        if left > REFRESH_BEFORE_DAYS * 86400 or now - (rec.get("saved_at") or 0) < 86400 or left <= 0:
            continue
        r = session.get(f"{GRAPH}/refresh_access_token", params={"grant_type": "th_refresh_token",
                                                                 "access_token": rec["access_token"]}, timeout=30).json()
        if r.get("access_token"):
            rec.update(access_token=r["access_token"], expires_at=now + float(r.get("expires_in") or 5184000),
                       saved_at=now)
            p.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            n += 1
        else:
            log(f"Threads token for {p.stem} not renewed: {str(r)[:120]}")
    return n


def text_for(meta: dict, youtube_id: str | None = None) -> str:
    """Conversational: the title, the first description line, the full-video link, one tag (Threads shows one)."""
    title = str(meta.get("title") or "").strip()
    desc = str(meta.get("description") or "").split("\n")[0].strip()
    if desc.lower().startswith(title.lower()[:30].lower()) and title:
        desc = ""
    tag = next((t if t.startswith("#") else "#" + t for t in (meta.get("hashtags") or []) if str(t).strip("#")), "")
    tag = re.sub(r"[^\w#]", "", tag)
    link = f"Full video: https://youtu.be/{youtube_id}" if youtube_id else ""
    if meta.get("campaign"):                              # paid campaign clip: the disclosure stays visible
        tag = "#ad"
    parts = [p for p in (title, desc) if p]
    tail = "\n\n".join(p for p in (link, tag) if p)
    body = "\n\n".join(parts)
    room = TEXT_MAX - (len(tail) + 2 if tail else 0)
    if len(body) > room:
        body = body[:max(0, room - 1)].rsplit(" ", 1)[0] + "…"
    return (body + ("\n\n" + tail if tail else "")).strip()[:TEXT_MAX]


def ig_video_url(channel_id: str, media_id: str, session=requests) -> str | None:
    """The published Reel's own video link from Instagram (public, short-lived): Threads fetches it once."""
    from .publish import GRAPH as FB_GRAPH, IG_GRAPH, meta_creds
    c = meta_creds(channel_id)
    if not (c and media_id):
        return None
    host = IG_GRAPH if c.get("login") == "instagram" else FB_GRAPH
    for _ in range(6):                                    # the link can lag a few seconds behind publishing
        r = session.get(f"{host}/{media_id}", params={"fields": "media_url,media_type",
                                                      "access_token": c["access_token"]}, timeout=30).json()
        if r.get("media_url"):
            return r["media_url"]
        time.sleep(5)
    return None


def post_video(channel_id: str, video_url: str, text: str, session=requests, dry_run: bool = True,
               item_id: str = "", poll_s: float = 10.0, max_polls: int = 60):
    from .publish import Action, _log
    act = Action("threads", channel_id, item_id, "publish Threads video", details={"chars": len(text)})
    c = None if dry_run else creds(channel_id)
    if not c:
        act.details["dry_run"] = True
        _log(act)
        return act
    uid, tok = c["user_id"], c["access_token"]
    lim = session.get(f"{GRAPH}/{VERSION}/{uid}/threads_publishing_limit",
                      params={"fields": "quota_usage", "access_token": tok}, timeout=30).json()
    if ((lim.get("data") or [{}])[0]).get("quota_usage", 0) >= DAILY_GUARD:
        act.result = {"error": "Threads daily posting guard reached"}
        _log(act)
        return act
    cont = session.post(f"{GRAPH}/{VERSION}/{uid}/threads", data={"media_type": "VIDEO", "video_url": video_url,
                                                                 "text": text[:TEXT_MAX], "access_token": tok},
                        timeout=60).json()
    if not cont.get("id"):
        act.result = {"error": "Threads refused the video: " + str(cont.get("error", {}).get("message") or cont)[:200]}
        _log(act)
        return act
    status = ""
    for _ in range(max_polls):                            # Threads downloads + processes the video first
        st = session.get(f"{GRAPH}/{VERSION}/{cont['id']}", params={"fields": "status,error_message",
                                                                    "access_token": tok}, timeout=30).json()
        status = st.get("status", "")
        if status in ("FINISHED", "PUBLISHED"):
            break
        if status in ("ERROR", "EXPIRED"):
            act.result = {"error": f"Threads could not process the video: {st.get('error_message') or status}"}
            _log(act)
            return act
        time.sleep(poll_s)
    if status not in ("FINISHED", "PUBLISHED"):
        act.result = {"error": "Threads was still processing the video after 10 minutes"}
        _log(act)
        return act
    pub = session.post(f"{GRAPH}/{VERSION}/{uid}/threads_publish", data={"creation_id": cont["id"],
                                                                         "access_token": tok}, timeout=60).json()
    if not pub.get("id"):
        act.result = {"error": "Threads didn't publish: " + str(pub.get("error", {}).get("message") or pub)[:200]}
        _log(act)
        return act
    act.done, act.result = True, {"thread_id": pub["id"]}
    _log(act)
    return act


def check(session=requests) -> list[dict]:
    """Doctor lines: each connected profile answers, and how long its login lasts."""
    out = []
    for p in sorted(SECRETS.glob("threads_*.json")) if SECRETS.exists() else []:
        cid = p.stem.replace("threads_", "", 1)
        c = creds(cid)
        if not c:
            continue
        try:
            me = session.get(f"{GRAPH}/{VERSION}/me", params={"fields": "username", "access_token": c["access_token"]},
                             timeout=20).json()
        except Exception as e:  # noqa: BLE001
            out.append({"area": f"Threads {cid}", "status": "warn", "seen": f"no answer ({type(e).__name__})", "fix": ""})
            continue
        days = ((c.get("expires_at") or 0) - time.time()) / 86400
        if me.get("username"):
            out.append({"area": f"Threads {cid}", "status": "good" if days > 7 else "warn",
                        "seen": f"@{me['username']} · login valid {days:.0f} days",
                        "fix": "" if days > 7 else "renews by itself; if it keeps failing, connect again"})
        else:
            out.append({"area": f"Threads {cid}", "status": "bad", "seen": str(me.get("error") or me)[:90],
                        "fix": "connect again in the setup assistant (Threads step)"})
    return out
