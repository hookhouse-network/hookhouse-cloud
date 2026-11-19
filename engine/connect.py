"""Week 3 helpers: connect accounts and fetch analytics (official Google / Meta flows only).

- connect_youtube(): OAuth 2.0 for installed apps. Opens Google's own consent page in the browser; a tiny local
  server on 127.0.0.1 receives the one-time code; we store only the refresh token in data/secrets (git-ignored).
  The owner signs in themselves; we never see or store the password.
- save_meta(): stores the Instagram user id + Page id + long-lived token the owner creates in Meta's tools.
- fetch_youtube_metrics(): YouTube Analytics API v2 per-video report -> analytics.record().
Needs YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET in .env (from the owner's own Google Cloud project).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from .publish import SECRETS, yt_access_token, yt_token_path
from engine.core.http import HTTP

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube",
          "https://www.googleapis.com/auth/youtube.force-ssl",          # captions upload (SEO v2)
          "https://www.googleapis.com/auth/yt-analytics.readonly"]


GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"      # send only: the system can never read the mailbox


def consent_url(client_id: str, redirect: str, state: str, scopes: list[str] | None = None) -> str:
    q = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(scopes or SCOPES),
         "access_type": "offline", "prompt": "consent", "state": state}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(q)


def connect_youtube(channel_id: str, port: int = 8799, timeout_s: int = 300, session=HTTP, opener=None) -> bool:
    tok = google_sign_in(SCOPES, port, timeout_s, session, opener, "Sign in with the Google account that owns this channel")
    if not tok:
        return False
    SECRETS.mkdir(parents=True, exist_ok=True)
    yt_token_path(channel_id).write_text(json.dumps({"refresh_token": tok["refresh_token"],
                                                     "access_token": tok.get("access_token"),
                                                     "expires_at": time.time() + tok.get("expires_in", 3600)}),
                                         encoding="utf-8")
    return True


GMAIL_TOKEN = SECRETS / "gmail_outreach.json"


def connect_gmail(port: int = 8799, timeout_s: int = 300, session=HTTP, opener=None) -> bool:
    """The HookHouse Gmail (never a personal address) for creator outreach: permission to SEND only."""
    tok = google_sign_in([GMAIL_SEND], port, timeout_s, session, opener, "Sign in with the HookHouse Gmail")
    if not tok:
        return False
    SECRETS.mkdir(parents=True, exist_ok=True)
    GMAIL_TOKEN.write_text(json.dumps({"refresh_token": tok["refresh_token"], "access_token": tok.get("access_token"),
                                       "expires_at": time.time() + tok.get("expires_in", 3600)}), encoding="utf-8")
    return True


def google_sign_in(scopes: list[str], port: int = 8799, timeout_s: int = 300, session=HTTP, opener=None,
                   prompt: str = "Sign in") -> dict | None:
    """OAuth 2.0 for installed apps: Google's own page, a one-time code to 127.0.0.1, then the token answer."""
    cid, secret = os.environ.get("YOUTUBE_CLIENT_ID"), os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("Add YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET to .env first (Google Cloud > Credentials > "
                           "OAuth client ID > Desktop app).")
    state, got = secrets.token_urlsafe(16), {}
    redirect = f"http://127.0.0.1:{port}/"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if (q.get("state") or [""])[0] == state and q.get("code"):
                got["code"] = q["code"][0]
                msg = "Connected. You can close this tab."
            else:
                msg = "Something went wrong (no code). Close this tab and try again."
            body = msg.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", port), H)
    th = threading.Thread(target=srv.handle_request, daemon=True)
    th.start()
    url = consent_url(cid, redirect, state, scopes)
    print(f"{prompt}:\n{url}")
    (opener or webbrowser.open)(url)
    th.join(timeout_s)
    srv.server_close()
    if not got.get("code"):
        return None
    r = session.post("https://oauth2.googleapis.com/token", data={
        "code": got["code"], "client_id": cid, "client_secret": secret, "redirect_uri": redirect,
        "grant_type": "authorization_code"}, timeout=30)
    r.raise_for_status()
    tok = r.json()
    if not tok.get("refresh_token"):
        raise RuntimeError("Google did not return a refresh token. Remove the app's access in your Google account "
                           "and connect again.")
    return tok


def meta_long_lived(token: str, session=HTTP) -> tuple[str, float | None]:
    """A token copied from Meta's tools lasts 1-2 hours. With META_APP_ID + META_APP_SECRET in .env it is swapped
    for a 60-day token (official fb_exchange_token flow). Without them the token is kept as it is."""
    app_id, secret = os.environ.get("META_APP_ID"), os.environ.get("META_APP_SECRET")
    if not app_id or not secret:
        return token, None
    from .publish import GRAPH
    r = session.get(f"{GRAPH}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": app_id,
                                                          "client_secret": secret, "fb_exchange_token": token},
                    timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], time.time() + float(d.get("expires_in") or 60 * 86400)


def meta_page_token(page_id: str, user_token: str, session=HTTP) -> str:
    """The Page's own token; made from a 60-day user token it does not expire (used for Facebook Reels)."""
    from .publish import GRAPH
    r = session.get(f"{GRAPH}/{page_id}", params={"fields": "access_token", "access_token": user_token}, timeout=30)
    return (r.json() or {}).get("access_token", "") if r.ok else ""


def ig_long_lived(token: str, session=HTTP) -> tuple[str, float | None]:
    """Instagram Login: short token -> 60-day token (ig_exchange_token); needs the app secret in .env."""
    secret = os.environ.get("META_APP_SECRET")
    if not secret:
        return token, None
    r = session.get("https://graph.instagram.com/access_token", params={
        "grant_type": "ig_exchange_token", "client_secret": secret, "access_token": token}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["access_token"], time.time() + float(d.get("expires_in") or 60 * 86400)


def refresh_instagram_tokens(session=HTTP) -> list[str]:
    """Instagram Login tokens last 60 days and can be renewed (ig_refresh_token) once they are a day old: done
    automatically when fewer than 20 days are left, so the owner never has to reconnect."""
    done = []
    for p in sorted(SECRETS.glob("meta_*.json")) if SECRETS.exists() else []:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            if not rec.get("expires_at"):
                continue
            if rec["expires_at"] - time.time() > 20 * 86400 or time.time() - (rec.get("saved_at") or 0) < 86400:
                continue
            if rec.get("login") != "instagram":      # 17 Nov: unified-login keys are Facebook-issued 60-day tokens;
                token, exp = meta_long_lived(rec["access_token"], session)   # re-exchanging gives a fresh 60 days
                if exp and token:
                    rec.update(access_token=token, saved_at=time.time(), expires_at=exp)
                    p.write_text(json.dumps(rec), encoding="utf-8")
                    done.append(p.stem.replace("meta_", "", 1))
                continue
            r = session.get("https://graph.instagram.com/refresh_access_token",
                            params={"grant_type": "ig_refresh_token", "access_token": rec["access_token"]}, timeout=30)
            d = r.json() if r.ok else {}
            if d.get("access_token"):
                rec.update(access_token=d["access_token"], saved_at=time.time(),
                           expires_at=time.time() + float(d.get("expires_in") or 60 * 86400))
                p.write_text(json.dumps(rec), encoding="utf-8")
                done.append(p.stem.replace("meta_", "", 1))
        except Exception:  # noqa: BLE001 - token_health reports what is left
            pass
    return done


def save_meta(channel_id: str, ig_user_id: str, page_id: str, access_token: str, page_token: str = "",
              session=HTTP, exchange: bool = True, login: str = "facebook", expires_at: float | None = None) -> dict:
    """login="facebook": Instagram via a Facebook Page (also allows Facebook Reels).
    login="instagram": Instagram API with Instagram Login, no Facebook Page needed (Facebook Reels only if a Page
    id and Page token are given too)."""
    if exchange and login == "instagram":
        access_token, expires_at = ig_long_lived(access_token, session)
    elif exchange:
        access_token, expires_at = meta_long_lived(access_token, session)
        if expires_at and not page_token and page_id:
            page_token = meta_page_token(page_id, access_token, session)
    rec = {"ig_user_id": ig_user_id, "page_id": page_id, "access_token": access_token, "page_token": page_token,
           "expires_at": expires_at, "saved_at": time.time(), "login": login}
    SECRETS.mkdir(parents=True, exist_ok=True)
    (SECRETS / f"meta_{channel_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


def token_health(session=HTTP) -> list[str]:
    """Logins that stopped working or end soon (checked every morning; the owner gets one phone message)."""
    from .publish import GRAPH, IG_GRAPH
    probs = []
    try:
        refresh_instagram_tokens(session)
    except Exception:  # noqa: BLE001
        pass
    for p in sorted(SECRETS.glob("youtube_*.json")) if SECRETS.exists() else []:
        cid = p.stem.replace("youtube_", "", 1)
        try:
            tok = json.loads(p.read_text(encoding="utf-8"))
            tok["expires_at"] = 0                                  # force a real refresh
            p.write_text(json.dumps(tok), encoding="utf-8")
            yt_access_token(cid, session)
        except requests.HTTPError as e:
            body = getattr(e.response, "text", "") or ""
            if "invalid_grant" in body:
                probs.append(f"YouTube login for {cid} stopped working: run python cli.py connect youtube --channel {cid}")
        except Exception:  # noqa: BLE001 - network: try again tomorrow
            pass
    for p in sorted(SECRETS.glob("meta_*.json")) if SECRETS.exists() else []:
        cid = p.stem.replace("meta_", "", 1)
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        left = ((rec.get("expires_at") or 0) - time.time()) / 86400
        if rec.get("expires_at") and left < 7:
            probs.append(f"Instagram/Facebook login for {cid} ends in {max(0, left):.0f} days: reconnect it (connect meta)")
            continue
        try:
            host = IG_GRAPH if rec.get("login") == "instagram" else GRAPH
            r = session.get(f"{host}/me", params={"fields": "id", "access_token": rec.get("access_token")}, timeout=30)
            if ((r.json() or {}).get("error") or {}).get("code") == 190:
                probs.append(f"Instagram/Facebook login for {cid} has expired: reconnect it (connect meta)")
        except Exception:  # noqa: BLE001
            pass
    return probs


YT_METRICS = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained"


def fetch_youtube_metrics(channel_id: str, video_id: str, start: str, end: str, session=HTTP) -> dict | None:
    """Per-video totals from the YouTube Analytics API (dates YYYY-MM-DD). None if the channel isn't connected.
    {} when YouTube has no rows yet (Analytics runs 2-3 days behind): callers must NOT save that as zero views
    (18 Nov: every 2 h / 24 h snapshot was stored as 0 and never fetched again). engagedViews (the Shorts
    monetisation count since March 2025) is asked for first; an API that refuses it gets the classic list."""
    token = yt_access_token(channel_id, session)
    if not token:
        return None
    if start > end:                                   # a scheduled video that isn't public yet
        return {}
    for metrics in (YT_METRICS + ",engagedViews", YT_METRICS):
        r = session.get("https://youtubeanalytics.googleapis.com/v2/reports",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": metrics,
                                "filters": f"video=={video_id}"}, timeout=30)
        if getattr(r, "status_code", 200) == 400 and metrics != YT_METRICS:
            continue
        r.raise_for_status()
        break
    data = r.json()
    heads = [h["name"] for h in data.get("columnHeaders", [])]
    rows = data.get("rows") or []
    return dict(zip(heads, rows[0])) if rows else {}
