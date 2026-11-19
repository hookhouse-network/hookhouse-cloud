"""Live checks for every connection (owner, 12 Nov 2026: "live checks ... sort it out"). Read-only calls only:
nothing is posted, nothing is changed on any platform. Run `python cli.py doctor` or send /doctor to the bot; it also
runs when the bot starts, so problems show up the moment an account is added.
Each result: (area, status good/warn/bad/info, what we saw, how to fix it)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import requests

from .config import ROOT
from engine.core.http import HTTP

SECRETS = ROOT / "data" / "secrets"


def _r(area, status, seen, fix=""):
    return {"area": area, "status": status, "seen": seen, "fix": fix}


def telegram(session=HTTP) -> list[dict]:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        return [_r("Telegram", "bad", "no bot token", "Phase 1: token from @BotFather into .env (TELEGRAM_BOT_TOKEN=)")]
    try:
        me = session.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20).json()
    except Exception as e:  # noqa: BLE001
        return [_r("Telegram", "warn", f"no answer ({type(e).__name__})", "check the internet connection")]
    if not me.get("ok"):
        return [_r("Telegram", "bad", f"token refused: {me.get('description')}", "copy the token again from @BotFather")]
    out = [_r("Telegram", "good", f"bot @{me['result'].get('username')} works")]
    out.append(_r("Telegram phone", "good" if os.environ.get("TELEGRAM_CHAT_ID") else "bad",
                  "paired" if os.environ.get("TELEGRAM_CHAT_ID") else "not paired",
                  "" if os.environ.get("TELEGRAM_CHAT_ID") else "run: python cli.py bot pair, send the code to the bot"))
    return out


def youtube(session=HTTP) -> list[dict]:
    from .publish import _quota_state, yt_access_token
    out = []
    if not (os.environ.get("YOUTUBE_CLIENT_ID") and os.environ.get("YOUTUBE_CLIENT_SECRET")):
        out.append(_r("YouTube app", "bad", "no Google OAuth client in .env",
                      "Phase 4: YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET (Google Cloud > Credentials)"))
    files = sorted(SECRETS.glob("youtube_*.json")) if SECRETS.exists() else []
    if not files:
        out.append(_r("YouTube channels", "bad", "no channel connected", "python cli.py connect youtube --channel <n>"))
    for p in files:
        cid = p.stem.replace("youtube_", "", 1)
        try:
            tok = yt_access_token(cid, session)
            r = session.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet,status",
                                                                                     "mine": "true"},
                            headers={"Authorization": f"Bearer {tok}"}, timeout=20)
            items = (r.json() or {}).get("items") or []
            if items:
                st = items[0].get("status") or {}
                out.append(_r(f"YouTube {cid}", "good", f"connected to \"{items[0]['snippet'].get('title')}\""
                              + (" · long uploads allowed" if st.get("longUploadsStatus") == "allowed" else
                                 " · not verified for videos over 15 min"),
                              "" if st.get("longUploadsStatus") == "allowed" else "verify the channel: youtube.com/verify"))
            else:
                out.append(_r(f"YouTube {cid}", "bad", f"login works but no channel (HTTP {r.status_code})",
                              "reconnect and pick the channel's Brand Account in Google's window"))
        except Exception as e:  # noqa: BLE001
            out.append(_r(f"YouTube {cid}", "bad", f"login failed: {str(e)[:80]}",
                          f"python cli.py connect youtube --channel {cid}"))
    q = _quota_state()
    out.append(_r("YouTube quota", "info", f"today: uploads {q.get('insert_used', 0)} units, other {q.get('used', 0)} units"))
    return out


def meta(session=HTTP) -> list[dict]:
    from .publish import GRAPH, IG_GRAPH
    out = []
    files = sorted(SECRETS.glob("meta_*.json")) if SECRETS.exists() else []
    if not files:
        return [_r("Instagram/Facebook", "bad", "no account connected", "Phase 3 + setup guide step 8 (Meta app)")]
    if not (os.environ.get("META_APP_ID") and os.environ.get("META_APP_SECRET")):
        out.append(_r("Meta app keys", "warn", "META_APP_ID / META_APP_SECRET missing",
                      "add them to .env, then reconnect for 60-day tokens"))
    for p in files:
        cid = p.stem.replace("meta_", "", 1)
        rec = json.loads(p.read_text(encoding="utf-8"))
        host = IG_GRAPH if rec.get("login") == "instagram" else GRAPH
        try:
            r = session.get(f"{host}/{rec['ig_user_id']}", params={"fields": "username,followers_count",
                                                                   "access_token": rec["access_token"]}, timeout=20).json()
            if r.get("username"):
                days = ((rec.get("expires_at") or 0) - time.time()) / 86400
                out.append(_r(f"Instagram {cid}", "good" if not rec.get("expires_at") or days > 7 else "warn",
                              f"@{r['username']} · {r.get('followers_count', 0)} followers"
                              + (f" · login valid {days:.0f} days" if rec.get("expires_at") else ""),
                              "" if not rec.get("expires_at") or days > 7 else "reconnect soon (connect meta)"))
            else:
                out.append(_r(f"Instagram {cid}", "bad", str((r.get("error") or {}).get("message", r))[:90],
                              "reconnect: python cli.py connect meta ..."))
        except Exception as e:  # noqa: BLE001
            out.append(_r(f"Instagram {cid}", "warn", f"no answer ({type(e).__name__})", "check the internet"))
        if rec.get("page_id"):
            out.append(_r(f"Facebook {cid}", "good" if rec.get("page_token") else "warn",
                          "Page token saved" if rec.get("page_token") else "no Page token (Reels use the user token)",
                          "" if rec.get("page_token") else "add META_APP_ID/SECRET and reconnect"))
    return out


def threads(session=HTTP) -> list[dict]:
    from .threads import check
    return check(session)


def dailymotion(session=HTTP) -> list[dict]:
    from .publish import _dm_token, dm_creds
    from .config import channels
    out = []
    have = [c["id"] for c in channels() if dm_creds(c["id"])]
    if not have:
        return [_r("Dailymotion", "warn", "not connected", "setup guide phase 8: private API key from Dailymotion Studio")]
    for cid in have:
        try:
            _dm_token(dm_creds(cid), session)
            out.append(_r(f"Dailymotion {cid}", "good", "API key works"))
        except Exception as e:  # noqa: BLE001
            out.append(_r(f"Dailymotion {cid}", "bad", f"key refused: {str(e)[:80]}", "create a new private API key"))
    return out


def local() -> list[dict]:
    out = []
    free = shutil.disk_usage(ROOT).free / 1e9
    out.append(_r("Disk D:", "good" if free >= 15 else "warn" if free >= 10 else "bad", f"{free:.0f} GB free",
                  "" if free >= 15 else "free space on D: (long videos need 10 GB)"))
    try:
        from .media import ffmpeg
        ffmpeg.ffmpeg_bin()
        out.append(_r("ffmpeg", "good", "found"))
    except Exception as e:  # noqa: BLE001
        out.append(_r("ffmpeg", "bad", str(e)[:80], "reinstall ffmpeg"))
    for mod, why in (("kokoro", "voices"), ("pyworld", "Bloop singing")):
        try:
            __import__(mod)
            out.append(_r(f"Python: {mod}", "good", f"installed ({why})"))
        except Exception:  # noqa: BLE001
            out.append(_r(f"Python: {mod}", "bad", "missing", f"python -m pip install {mod}"))
    hb = ROOT / "data" / "state" / "heartbeat.txt"
    age = time.time() - hb.stat().st_mtime if hb.exists() else None
    out.append(_r("Autopilot", "good" if age is not None and age < 600 else "bad",
                  "running" if age is not None and age < 600 else "not running",
                  "" if age is not None and age < 600 else "double-click scripts/telegram_bot.cmd (or setup_pc.cmd once)"))
    try:
        q = subprocess.run(["schtasks", "/Query", "/TN", "HookHouse Autopilot"], capture_output=True, text=True,
                           timeout=20)
        out.append(_r("Start with Windows", "good" if q.returncode == 0 else "warn",
                      "scheduled task found" if q.returncode == 0 else "no scheduled task",
                      "" if q.returncode == 0 else "double-click scripts/setup_pc.cmd once"))
    except Exception:  # noqa: BLE001
        pass
    keys = {"CLOUDFLARE_API_TOKEN": "AI images", "YOUTUBE_API_KEY": "weekly 'what's winning' search",
            "PEXELS_API_KEY": "stock footage", "GEMINI_API_KEY": "backup writer", "GROQ_API_KEY": "backup writer"}
    missing = [f"{k} ({v})" for k, v in keys.items() if not os.environ.get(k)]
    out.append(_r("Free API keys", "good" if not missing else "warn",
                  "all set" if not missing else "missing: " + ", ".join(missing), "" if not missing else
                  "setup guide phase 6"))
    return out


def extras() -> list[dict]:
    """Things the system now does by itself, once they're connected: channel pages and outreach email."""
    out = []
    from . import branding, gmail
    from .config import channels
    from .publish import yt_token_path
    conn = sum(1 for c in channels() if yt_token_path(c["id"]).exists())
    if conn:
        n = branding.done_count()
        out.append(_r("YouTube channel pages", "good" if n >= conn else "warn", f"{n}/{conn} written by the API",
                      "" if n >= conn else "written at 09:00 by the autopilot (or: reconnect the channel)"))
    ok, why = gmail.ready()
    out.append(_r("Outreach email", "good" if ok else "warn", "sends after your tap (send-only)" if ok else "by hand",
                  "" if ok else why))
    return out


def run(session=HTTP) -> list[dict]:
    out = []
    for fn in (local, telegram, youtube, meta, threads, dailymotion, extras):
        try:
            out += fn() if fn in (local, extras) else fn(session)
        except Exception as e:  # noqa: BLE001 - one check failing must not hide the others
            out.append(_r(fn.__name__, "warn", f"check failed: {type(e).__name__}: {str(e)[:80]}"))
    (ROOT / "data" / "state").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "state" / "doctor.json").write_text(json.dumps({"at": time.time(), "results": out}, indent=1),
                                                          encoding="utf-8")
    return out


def text(results: list[dict]) -> str:
    icon = {"good": "✅", "warn": "⚠️", "bad": "❌", "info": "ℹ️"}
    bad = sum(1 for r in results if r["status"] == "bad")
    lines = [f"🩺 HookHouse check: {bad} to fix" if bad else "🩺 HookHouse check: all connections work"]
    for r in results:
        lines.append(f"{icon.get(r['status'], '•')} {r['area']}: {r['seen']}" + (f"\n   → {r['fix']}" if r["fix"] else ""))
    if bad:
        lines.append("Fastest way to fix the accounts and keys: double-click scripts/setup_accounts.cmd (setup assistant).")
    return "\n".join(lines)
