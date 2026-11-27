"""Telegram control bot: campaign picks, status and alerts on the owner's phone (official Telegram Bot API only).

- digest(): every morning (after `campaign discover`) sends the best campaigns as ONE message with a tick box per
  campaign. The owner ticks several and presses Confirm. Picked campaigns get status "picked"; the bot replies with
  each campaign's join link (joining happens on the board's own site; there is no official join API).
- run(): the listener that receives the taps (long polling). Only the owner's chat is answered.
- Pairing: `python cli.py bot pair` prints a one-time code; sending it to the bot saves the owner's chat id in .env.
- notify(text): alerts from any part of the system (failed jobs, copyright claims, budget warnings).
Nothing here posts publicly or joins anything by itself.
"""
from __future__ import annotations
from engine.core.quiet import noted

import json
import os
import secrets
import sys
import time

import requests

from . import config  # noqa: F401  (loads .env into os.environ)
from .config import ROOT

STATE = ROOT / "data" / "telegram" / "state.json"
PAIR = ROOT / "data" / "telegram" / "pair_code.txt"
PICKS = ROOT / "data" / "telegram" / "picks.jsonl"
SAID = ROOT / "data" / "telegram" / "owner_said.jsonl"    # the owner's typed messages (cloud memory, read by Claude)
SAID_KEEP = 300
CHOICES = ROOT / "config" / "owner_choices.yaml"
VOICES = ROOT / "data" / "review" / "voice_samples"
DIGEST_SIZE = 10


class NotConfigured(RuntimeError):
    pass


# ---------------- Telegram API ----------------
def _token() -> str:
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not t:
        raise NotConfigured("Add TELEGRAM_BOT_TOKEN to .env (from @BotFather).")
    return t


def _chat() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def api(method: str, files: dict | None = None, http_timeout: float = 30, **params):
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    for attempt in range(3):
        if files:
            for f in files.values():                       # a retry must send the file from the start again
                if hasattr(f[1], "seek"):
                    f[1].seek(0)
            r = requests.post(url, data={k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                         for k, v in params.items()}, files=files, timeout=http_timeout)
        else:
            r = requests.post(url, json=params, timeout=http_timeout)
        try:
            data = r.json()
        except ValueError:
            data = {"ok": False, "description": f"HTTP {r.status_code}"}
        if data.get("ok"):
            return data["result"]
        wait = (data.get("parameters") or {}).get("retry_after")
        if (wait or r.status_code >= 500) and attempt < 2 and method != "getUpdates":
            time.sleep(min(float(wait or 5), 60))           # Telegram asked us to slow down, or a server blip
            continue
        raise RuntimeError(f"Telegram {method}: {data.get('description')}")
    raise RuntimeError(f"Telegram {method}: no answer")


def send(text: str, chat: str | None = None, **kw):
    chat = chat or _chat()
    if not chat:
        raise NotConfigured("No TELEGRAM_CHAT_ID yet: run `python cli.py bot pair` and send the code to the bot.")
    kw.setdefault("disable_notification", quiet_hours())
    return api("sendMessage", chat_id=chat, text=text[:4096], disable_web_page_preview=True, **kw)


def quiet_hours() -> bool:
    """23:00-07:00 India time: messages arrive silently (US posting times would otherwise buzz all night)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    h = datetime.now(ZoneInfo("Asia/Kolkata")).hour
    return h >= 23 or h < 7


def notify(text: str) -> bool:
    """Alert the owner; never raises (alerts must not break the job that sends them)."""
    try:
        send("🔔 " + text)
        return True
    except Exception as _swallowed:  # noqa: BLE001
        noted("telegram_bot.py:96", _swallowed)
        return False


# ---------------- the owner's own words ----------------
def note_owner_text(text: str, at: float | None = None) -> str:
    """22 Nov: a typed message from the owner that is not a command (an answer to a question Claude asked here, an
    idea, a correction) got the Worker's "working on it" and was then dropped by the cloud run without a trace, so the
    answers to Claude's questions never arrived. It is now kept in data/telegram/owner_said.jsonl (cloud memory, read
    by the plan loop every round) and in the ledger (event owner_text), and the owner is told plainly where it went."""
    row = {"t": round(at or time.time(), 1), "text": text[:2000]}
    try:
        SAID.parent.mkdir(parents=True, exist_ok=True)
        lines = SAID.read_text(encoding="utf-8").splitlines() if SAID.exists() else []
        lines = (lines + [json.dumps(row, ensure_ascii=False)])[-SAID_KEEP:]
        SAID.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:                     # the ledger copy below still holds it (said, never silent)
        file_log(f"owner message not saved to {SAID.name}: {type(e).__name__}: {e}")
    from .core import ledger
    ledger.event("owner_text", data=row)
    short = text if len(text) <= 160 else text[:157] + "..."
    return (f"📝 Saved for Claude: “{short}”\nClaude reads your messages at every check (about once an hour) "
            "and answers here. Buttons and commands still work as before (/menu).")


def owner_said(since: float = 0.0) -> list[dict]:
    """The owner's typed messages from `since` on, oldest first (a damaged line is skipped, the rest still count)."""
    if not SAID.exists():
        return []
    out = []
    for line in SAID.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError as e:
            file_log(f"{SAID.name}: damaged line skipped ({e})")
            continue
        if isinstance(row, dict) and float(row.get("t") or 0) >= since:
            out.append(row)
    return out


# ---------------- state ----------------
def _load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def _save(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


# ---------------- campaign digest ----------------
def candidates(conn=None, limit: int = DIGEST_SIZE, fresh_only: bool = True) -> list[dict]:
    from . import db
    conn = conn or db.connect()
    rows = db.list_campaigns(conn, "eligible") + db.list_campaigns(conn, "review")
    shown = _load().get("shown", {})
    soon = time.time() + 36 * 3600                          # budget gone before our clips could be posted
    rows = [c for c in rows if not c.get("drain_at") or _ts(c["drain_at"]) > soon]
    rows = [c for c in rows if not _needs_face(c)]           # faceless channels: UGC "film yourself" briefs never fit
    fresh = [c for c in rows if shown.get(c["id"], 0) < 3]  # passed over on 3 mornings: stop repeating it
    rows = fresh if fresh_only else rows
    rows.sort(key=lambda c: (c.get("fit") == "OK", (c.get("score") or 0) + (c.get("hot_boost") or 0),
                             c.get("cpm_usd") or 0), reverse=True)
    return rows[:limit]


BOARDS_WE_USE = ("Content Rewards",)          # boards with a HookHouse account (Vyro after its setup)


def joinable(c: dict) -> bool:
    """A picked campaign worth a Join tap: on a board we have an account on, and footage we can legally use."""
    return c.get("board") in BOARDS_WE_USE and not _needs_face(c)


def _needs_face(c: dict) -> bool:
    """Campaigns we can never fulfil: UGC 'film yourself' briefs (faceless channels), and footage that exists only on
    the creator's own YouTube/Twitch channels (we never download from video platforms) - 17 Nov: 3 of 10 picks."""
    kind = f"{c.get('campaign_type') or ''} {c.get('content_type') or ''} {c.get('name') or ''}".lower()
    sources = " ".join(str(x) for x in c.get("allowed_sources") or []).lower()
    return "ugc" in kind or "creator's channel" in sources or "creators channel" in sources


def _ts(iso: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")


def _line(i: int, c: dict) -> str:
    mark = "✅" if c.get("fit") == "OK" else "⚠️"
    bits = []
    if c.get("cpm_usd"):
        bits.append(f"${c['cpm_usd']}/1K views")
    if c.get("budget_left_pct") is not None:
        bits.append(f"{c['budget_left_pct']:.0f}% budget left")
    if c.get("drain_at") and _ts(c["drain_at"]) < float("inf"):
        bits.append("runs out ~" + time.strftime("%d %b", time.localtime(_ts(c["drain_at"]))))
    if c.get("platforms"):
        bits.append("/".join(p.replace("youtube_shorts", "YT").replace("instagram_reels", "IG")
                             .replace("tiktok", "TT") for p in c["platforms"]))
    why = "; ".join(str(r) for r in (c.get("fit_reasons") or [])[:2])
    acct = f" → {c['account']}" if c.get("account") else ""
    return (f"{i}. {mark} {c.get('brand') or ''} · {c.get('name', '')[:60]}{acct}\n   " + " · ".join(bits) +
            (f"\n   🔥 {', '.join(c['hot'][:2])}" if c.get("hot") else "") +
            (f"\n   {why[:140]}" if why else ""))


def _keyboard(n: int, picked: set[int]) -> dict:
    rows, row = [], []
    for i in range(n):
        row.append({"text": ("☑️ " if i in picked else "⬜ ") + str(i + 1), "callback_data": f"t:{i}"})
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": f"✅ Confirm {len(picked)} picked", "callback_data": "c"},
                 {"text": "All ✅ ones", "callback_data": "a"}, {"text": "🔄 Refresh", "callback_data": "r"}])
    return {"inline_keyboard": rows}


def ticked_in(markup: dict | None) -> list[int] | None:
    """Box numbers ticked (☑️) on a digest keyboard; None when the message carries no tick buttons."""
    btns = [b for r in (markup or {}).get("inline_keyboard", []) for b in r
            if str(b.get("callback_data", "")).startswith("t:")]
    if not btns:
        return None
    return [int(b["callback_data"][2:]) for b in btns if str(b.get("text", "")).startswith("☑️")]


def digest_text(rows: list[dict]) -> str:
    if not rows:
        return "📋 No new campaigns fit us today. I'll check again tomorrow."
    ok = sum(1 for c in rows if c.get("fit") == "OK")
    head = (f"💰 Campaigns for {time.strftime('%d %b')}: {ok} good ✅, {len(rows) - ok} maybe ⚠️\n"
            "1) Tap the numbers you want (☑️ = picked)\n2) Press ✅ Confirm\n"
            "3) I send a 🔗 Join button for each: open it and press Join Campaign\n\n")
    return head + "\n\n".join(_line(i + 1, c) for i, c in enumerate(rows))


def digest(conn=None, fresh_only: bool = True, check_live: bool = True) -> dict | None:
    rows = candidates(conn, fresh_only=fresh_only)
    if check_live and rows:
        try:                                        # never offer a campaign that was paused or ended meanwhile
            from . import discover
            rows = discover.refresh_states(rows, conn=conn)
            rows = candidates(conn, fresh_only=fresh_only) if len(rows) < DIGEST_SIZE else rows
            rows = discover.refresh_states(rows, conn=conn)
        except Exception as _swallowed:  # noqa: BLE001 - the list still goes out
            noted("telegram_bot.py:247", _swallowed)
            pass
    if not rows:
        send(digest_text(rows))
        return None
    msg = send(digest_text(rows), reply_markup=_keyboard(len(rows), set()))
    s = _load()
    s["digest"] = {"message_id": msg["message_id"], "ids": [c["id"] for c in rows], "picked": []}
    lists = s.setdefault("digests", {})                 # every list keeps its own ids: Confirm on an older list works
    lists[str(msg["message_id"])] = [c["id"] for c in rows]
    for k in sorted(lists, key=int)[:-10]:
        lists.pop(k)
    shown = s.setdefault("shown", {})
    for c in rows if fresh_only else []:            # only the morning list counts as "shown"
        shown[c["id"]] = shown.get(c["id"], 0) + 1
    _save(s)
    return msg


def confirm(ids: list[str], conn=None) -> str:
    """Mark campaigns as picked by the owner and return the reply with their join links."""
    from . import db
    conn = conn or db.connect()
    lines = []
    for cid in ids:
        c = db.get_campaign(conn, cid)
        if not c:
            continue
        c["status"], c["picked_at"] = "picked", time.time()
        db.save_campaign(conn, c)
        PICKS.parent.mkdir(parents=True, exist_ok=True)
        with PICKS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "id": cid, "name": c.get("name")}) + "\n")
        # 20 Nov (owner: "the join should be done through the system that we build"; "make sure you find the
        # footage ... I don't want any issues after joining"): footage first, then the system joins for the owner
        try:
            from .picker import footage_check
            fv, fwhy = footage_check(c)
        except Exception as e:  # noqa: BLE001 - not confirmed = not joined
            fv, fwhy = "unknown", f"footage check failed ({type(e).__name__})"
        if fv == "ok":
            from .campaign_join import request
            request(cid, by="owner (Telegram Confirm)")
            lines.append(f"• {c.get('name', '')[:60]}: ✅ footage confirmed ({fwhy}); joining it for you now"
                         + _footage_note(c))
        else:
            lines.append(f"• {c.get('name', '')[:60]}: 🛑 not joined: footage {fv} ({fwhy})")
    if not lines:
        return "Nothing was ticked. Tap the numbers first (☑️), then ✅ Confirm."
    return (f"👍 {len(lines)} campaign(s):\n" + "\n".join(lines) +
            "\n\nThe system presses Join on each confirmed campaign by itself and tells you here when it is done. "
            "Then it fetches the footage and sends every clip here for your ✅.")


def _footage_note(c: dict) -> str:
    """Add the campaign's direct footage files as clip sources (so its clip slots start by themselves)."""
    if not c.get("ca_ref"):
        return ""
    try:
        from . import discover, weekly
        f = discover.campaign_footage(c["ca_ref"])
    except Exception:  # noqa: BLE001 - the owner can still send /source
        return "\n  Footage: send its Google Drive/Dropbox file link with /source."
    if f["files"]:
        have = {s["source"] for s in weekly._read_sources()}
        new = [u for u in f["files"] if u not in have][:10]
        if new:
            weekly.CLIP_SOURCES.parent.mkdir(parents=True, exist_ok=True)
            with weekly.CLIP_SOURCES.open("a", encoding="utf-8") as fh:
                fh.writelines(f"{u} {c['id']}\n" for u in new)
        return f"\n  📥 Footage: {len(f['files'])} file(s) from the campaign added; clips start by themselves."
    if f["platform_pages"]:
        return ("\n  Footage: only Twitch/YouTube page links, which I never download. After joining, open the campaign's "
                "files (Drive/Dropbox) and send a file link with /source.")
    return "\n  Footage: none listed yet. After joining, send the campaign's file link with /source."


# ---------------- other commands ----------------
def status_text() -> str:
    """📊 Today (owner 17 Nov: plain and useful): videos made / waiting / posted, live views, campaigns, problems."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from . import autopilot, db, watchdog
    from .stats_fetch import live_stats
    ist = ZoneInfo("Asia/Kolkata")
    now = datetime.now(ist)
    today = now.date()
    try:
        items = [it for _, it in autopilot.items(2, 3)]
    except Exception:  # noqa: BLE001
        items = []

    def day(ts):
        return datetime.fromtimestamp(float(ts), ist).date() if ts else None
    made = [it for it in items if day(it.get("made_at")) == today]
    waiting = [it for it in items if it.get("status") == "made"]
    posted = [it for it in items if it.get("status") in ("posted", "scheduled") and autopilot._when(it).date() == today]
    upcoming = [it for it in items if it.get("status") == "approved" and autopilot._when(it) > now
                and autopilot._when(it) < now + timedelta(hours=24)]
    failed = [it for it in items if it.get("status") in ("failed", "needs_source") and autopilot._when(it) > now]
    live = live_stats()
    views = sum(int(v.get("views") or 0) for v in (live.get("videos") or {}).values())
    subs = sum(int(c.get("subs") or 0) for c in (live.get("channels") or {}).values())
    best = max((live.get("videos") or {}).values(), key=lambda v: int(v.get("views") or 0), default=None)
    conn = db.connect()
    camp = {st: len(db.list_campaigns(conn, st)) for st in ("picked", "joined")}
    try:
        probs = watchdog.problems(None)
    except Exception:  # noqa: BLE001
        probs = {}
    lines = [f"📊 Today, {now.strftime('%d %b %H:%M')}",
             "",
             f"🎬 Made today: {len(made)}  ·  📥 Waiting for your OK: {len(waiting)}",
             f"📤 Posting today: {len(posted)}  ·  ⏭️ Approved for the next 24 h: {len(upcoming)}",
             f"👀 Views so far (all videos): {views:,}  ·  👥 Subscribers: {subs:,}"]
    if best:
        lines.append(f"🏆 Best video: {best.get('title', '')[:50]} ({int(best.get('views') or 0):,} views)")
    lines.append(f"💰 Campaigns: {camp['picked']} picked (waiting for your Join), {camp['joined']} joined")
    if failed:
        lines.append(f"⏳ Waiting to be made again: {len(failed)} (free limits or footage; they retry by themselves)")
    lines.append("")
    if probs:
        lines.append("⚠️ Needs attention:")
        lines += [f"• {t[:160]}" for t in list(probs.values())[:4]]
    else:
        lines.append("✅ Everything is working.")
    if waiting:
        lines.append("\n👉 Tap 📥 Waiting for me to approve.")
    return "\n".join(lines)


def channels_text() -> str:
    """Per-channel numbers for the phone (same source as the dashboard's insights table)."""
    from .config import channels
    from .dashboard import _insight, _metrics
    metrics = _metrics()
    lines = []
    for ch in channels():
        m = metrics.get(ch["id"], {})
        if m:
            lines.append(f"• {ch['name']}: {m['videos']} videos · {m['views']:,} views ({m['views_7d']:,} this week) · "
                         f"+{m['subs']} subs · stayed {m['stayed'] if m['stayed'] is not None else '-'}%\n"
                         f"  {_insight(m)}")
        else:
            lines.append(f"• {ch['name']}: not live yet")
    head = "📺 Channel insights\n" + ("" if metrics else "No live numbers yet: they start once accounts are connected.\n")
    return head + "\n".join(lines)


def studio_button(link: str | None = None) -> bool:
    """Owner 19 Nov: "make the Telegram process simple, clear, fast". Telegram's menu button (Bot API
    setChatMenuButton, type web_app) opens the live Studio inside Telegram in one tap: review player, Approve & post /
    Change / Reject, calendar, numbers, with no link to find and no waiting for a cloud run to answer. Set for the
    owner's chat only (the link carries the private dashboard key); re-set every morning, so it heals itself."""
    if link is None:
        from .pc_fallback import dash_link
        link = dash_link()
    chat = _chat()
    if not (link and link.startswith("https://") and chat):
        return False
    return bool(api("setChatMenuButton", chat_id=chat,
                    menu_button={"type": "web_app", "text": "🎬 Studio", "web_app": {"url": link}}))


def send_dashboard() -> None:
    """Rebuild the monitoring pad and send it as a file: tap it on the phone to open the full page."""
    from .dashboard import build
    path = build()
    with path.open("rb") as fh:
        api("sendDocument", files={"document": ("HookHouse_dashboard.html", fh, "text/html")}, chat_id=_chat(),
            caption=f"📊 Monitoring pad, {time.strftime('%d %b %H:%M')}. Tap to open.", http_timeout=120)


def report() -> None:
    """Morning report: status + channel numbers + the full dashboard file."""
    send(status_text())
    send(channels_text())
    send_dashboard()


def health_digest() -> str:
    """P2b daily health digest (27 Nov): what is broken (the /health answer) and what needs the owner (the /tasks
    answer), in one morning message, so the owner reads one thing instead of asking."""
    parts = ["🩺 Morning health check"]
    for title, fn in (("System", health_text), ("Needs you", tasks_text)):
        try:
            body = (fn() or "").strip()
        except Exception as e:  # noqa: BLE001 - one part failing still sends the other (said in the message)
            body = f"(could not read: {type(e).__name__})"
        parts.append(f"— {title} —\n{body[:1500] or 'nothing'}")
    return "\n\n".join(parts)


def send_songs() -> None:
    """The Bloop songs (data/products/music) as phone-friendly MP3s, to listen before releasing them."""
    from .media import ffmpeg
    music = ROOT / "data" / "products" / "music"
    tracks = sorted(music.glob("*.wav")) if music.exists() else []
    if not tracks:
        send("No songs yet. On the PC: python -c \"from engine import songs; songs.album()\"")
        return
    prev = ROOT / "data" / "telegram" / "previews"
    prev.mkdir(parents=True, exist_ok=True)
    for t in tracks:
        mp3 = prev / f"{t.stem}.mp3"
        if not mp3.exists() or mp3.stat().st_mtime < t.stat().st_mtime:
            ffmpeg.run(["-i", str(t), "-b:a", "160k", str(mp3)])
        with mp3.open("rb") as fh:
            api("sendAudio", files={"audio": (mp3.name, fh, "audio/mpeg")}, chat_id=_chat(), performer="Bloop & Friends",
                title=t.stem.replace("_", " ").title(), http_timeout=180)
    send("🎵 The Bloop songs, in release order (the season's songs first). Each passed the automatic check: in tune, "
         "words clear to speech recognition, streaming loudness. Upload them with RouteNote (free; keep YouTube "
         "Content ID OFF); release.md has everything to type.")


def send_voices() -> None:
    files = sorted(VOICES.glob("*_line1.wav"))
    for f in files:
        with f.open("rb") as fh:
            api("sendAudio", files={"audio": (f.name, fh, "audio/wav")}, chat_id=_chat(),
                title=f.stem.split("_")[0], caption=f.stem.replace("_line1", "").replace("_", " "), http_timeout=120)
    letters = [f.stem.split("_")[0] for f in files]
    send("Which Hindi narrator voice do you like best?",
         reply_markup={"inline_keyboard": [[{"text": x, "callback_data": f"v:{x}"} for x in letters]]})


def save_choice(key: str, value: str) -> None:
    import yaml
    data = (yaml.safe_load(CHOICES.read_text(encoding="utf-8")) or {}) if CHOICES.exists() else {}
    data[key] = value
    data[key + "_chosen_at"] = time.strftime("%Y-%m-%d %H:%M")
    CHOICES.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


CHANGE_WAIT_S = 30 * 60          # after tapping Change, the next text counts as the change note for 30 minutes


# ---------------- /source: add clip footage from the phone ----------------
def source_start(link: str) -> None:
    """Owner sends `/source <Google Drive / Dropbox / direct file link>`; then picks which campaign it is for."""
    from .clips import PLATFORM_LINKS
    if not link.startswith(("http://", "https://")):
        send("Send it like this: /source https://drive.google.com/file/d/…\n"
             "Use the footage link from a campaign brief, or a file the creator shared with you in writing.")
        return
    if PLATFORM_LINKS.search(link):
        send("❌ I can't take YouTube/Twitch/Kick page links: their rules forbid downloading, and it causes copyright "
             "strikes. Use the campaign's source files (Google Drive / Dropbox link) or the creator's shared file.")
        return
    if "drive.google.com/drive/folders" in link:
        send("That's a Google Drive FOLDER. Open it, tap a video, Share → Copy link, and send that file link.")
        return
    from . import db
    camps = [c for st in ("joined", "picked") for c in db.list_campaigns(db.connect(), st)][:6]
    s = _load()
    s["pending_source"] = {"link": link, "camps": [c["id"] for c in camps], "at": time.time()}
    _save(s)
    rows = [[{"text": f"{(c.get('brand') or c.get('name') or '')[:40]}", "callback_data": f"s:{i}"}]
            for i, c in enumerate(camps)]
    rows.append([{"text": "Not a campaign (creator gave written permission)", "callback_data": "s:n"}])
    send("Which campaign is this footage for? (The clips follow that campaign's rules and go to its account.)",
         reply_markup={"inline_keyboard": rows})


def source_pick(choice: str) -> None:
    from . import weekly
    s = _load()
    p = s.pop("pending_source", None)
    _save(s)
    if not p:
        send("That button has expired. Send /source <link> again.")
        return
    camp = None
    if choice != "n":
        i = int(choice)
        camp = p["camps"][i] if i < len(p["camps"]) else None
    used = weekly.clip_state()["used"]
    lines = weekly.CLIP_SOURCES.read_text(encoding="utf-8").splitlines() if weekly.CLIP_SOURCES.exists() else []
    if p["link"] in used or any(ln.split()[:1] == [p["link"]] for ln in lines):
        send("I already have that footage, so I won't clip it twice.")
        return
    from . import clips
    try:
        files = clips.expand_source(p["link"])            # a shared Drive folder -> its video files
    except Exception:  # noqa: BLE001
        files = []
    if not files:
        send("I couldn't open that folder. In Google Drive set it to 'Anyone with the link can view', then send it again.")
        return
    weekly.CLIP_SOURCES.parent.mkdir(parents=True, exist_ok=True)
    with weekly.CLIP_SOURCES.open("a", encoding="utf-8") as f:
        f.writelines(f"{u}{(' ' + camp) if camp else ''}\n" for u in files)
    if camp and len(files) > 1:
        send(f"📥 {len(files)} videos found in that folder and saved. I'll cut the best moments into clips for the next "
             "clip slots and send each one here for your approval.")
    elif camp:
        send("📥 Footage saved. I'll cut the best moments into clips for the next clip slots and send each one here "
             "for your approval.")
    else:
        send("📥 Footage saved. Before I can clip it, its written permission must be on record: add the creator to "
             "config/clip_sources.yaml (basis written_permission + screenshot) on the PC. Without it I skip it.")


# ---------------- /queue: what is waiting ----------------
QUEUE_CARDS_MAX = 10
KIND_LABEL = {"short": "Short", "long": "Long video", "clip": "Clip", "story": "Short"}


def _card_title(it: dict) -> str:
    """The video's title (upload.json / clips.json), else its planned topic."""
    from pathlib import Path
    folder = Path(it.get("out_dir") or "")
    try:
        meta = json.loads((folder / "upload.json").read_text(encoding="utf-8"))
        if meta.get("title"):
            return str(meta["title"])
    except (OSError, ValueError):
        pass
    try:
        for c in json.loads((folder / "clips.json").read_text(encoding="utf-8")):
            if c.get("file") == it.get("file") and c.get("title"):
                return str(c["title"])
    except (OSError, ValueError, TypeError):
        pass
    return str(it.get("topic") or it.get("planned_topic") or "(untitled)")


def queue_cards() -> dict:
    """Owner 20 Nov: "telegram must have a button for waiting for approval that gives the list of videos that need my
    approval". Every video waiting for the owner (any day, soonest slot first), one card each with ✅ / ✏️ / ❌.
    Only videos that already passed the campaign + reach gates (= were offered once) get buttons; ones still being
    checked are counted, never shown with buttons (the gates stay in charge). Kept in the snapshot so the Worker
    answers the button at once."""
    from . import autopilot
    s = autopilot._load()
    waiting = sorted(((st, it) for st, it in autopilot.items(3, 14) if it["status"] == "made"),
                     key=lambda x: autopilot._when(x[1]))
    ready = [(st, it) for st, it in waiting if autopilot.asked_current(s, it)]
    checking = len(waiting) - len(ready)
    cards = []
    for st, it in ready[:QUEUE_CARDS_MAX]:
        tok = autopilot.token(st, it["id"], str(it.get("made_at") or ""))
        text = (f"🎬 {it.get('channel_name') or it['channel']} · {KIND_LABEL.get(it.get('kind'), it.get('kind', ''))}\n"
                f"{_card_title(it)[:180]}\n"
                f"⏰ posts {autopilot._when(it):%a %d %b, %H:%M}")
        cards.append({"tok": tok, "text": text, "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Approve & post", "callback_data": f"ap:{tok}"},
            {"text": "✏️ Change", "callback_data": f"ch:{tok}"},
            {"text": "❌ Reject", "callback_data": f"rj:{tok}"}]]}})
    if not waiting:
        header = "📥 Nothing is waiting for you right now. 👍"
    else:
        header = f"📥 {len(ready)} video(s) need your OK" + (f" · {checking} more being checked" if checking else "")
        if len(ready) > QUEUE_CARDS_MAX:
            header += f"\nShowing the first {QUEUE_CARDS_MAX}; the rest are in 🎬 Studio."
        header += "\nWatch any of them in 🎬 Studio (button left of the message box)."
    header_kb = ({"inline_keyboard": [[{"text": f"✅ Approve all {len(ready)}", "callback_data": "aa:all"}]]}
                 if len(ready) > 1 else None)
    return {"header": header, "header_kb": header_kb, "cards": cards, "count": len(ready), "checking": checking}


def send_queue() -> None:
    """📥 Waiting for me: the header, then one card per waiting video with its buttons."""
    q = queue_cards()
    send(q["header"], reply_markup=q["header_kb"]) if q["header_kb"] else send(q["header"])
    for c in q["cards"]:
        send(c["text"], reply_markup=c["reply_markup"])


# Owner 17 Nov 2026: "make the telegram smooth and easily understandable, i got confused". Six plain buttons stay at
# the bottom of the chat (a reply keyboard); every one maps to a command, so nothing has to be remembered.
MENU = {"📋 My tasks": "/tasks", "📥 Waiting for me": "/queue", "📊 Today": "/status", "💰 Campaigns": "/campaigns",
        "📈 Numbers": "/channels", "🛠️ Anything broken?": "/health", "❓ Help": "/help", "📺 Channels": "/pickmenu"}
MENU_KB = {"keyboard": [[{"text": "📋 My tasks"}, {"text": "📥 Waiting for me"}],
                        [{"text": "📊 Today"}, {"text": "💰 Campaigns"}],
                        [{"text": "📈 Numbers"}, {"text": "🛠️ Anything broken?"}],
                        [{"text": "📺 Channels"}, {"text": "❓ Help"}]],
           "resize_keyboard": True, "is_persistent": True}


# ---- P2b Telegram 2.0 (27 Nov): 📺 Channels -> one channel's menu -> 💡 Pick a topic in demand -> [Make it] ----
def channel_list_kb() -> dict:
    """One button per live channel."""
    from .config import channels
    rows, row = [], []
    for ch in channels():
        if not ch.get("enabled", True):
            continue
        row.append({"text": ch.get("name", ch["id"])[:28], "callback_data": f"chn:{ch['id']}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def channel_menu(cid: str) -> tuple[str, dict]:
    """One channel: videos waiting for approval, the next slots, and the Pick button."""
    from . import autopilot
    from .config import channel
    ch = channel(cid)
    items = [it for _s, it in autopilot.items(0, 3) if it.get("channel") == cid]
    waiting = sum(1 for it in items if it.get("status") == "made")
    nxt = [it for it in items if it.get("status") in ("planned", "redo", "making")][:3]
    lines = [f"📺 {ch.get('name', cid)}", f"Waiting for approval: {waiting}"]
    lines += ["Next:"] + [f"• {str(it.get('publish_at', ''))[5:16].replace('T', ' ')} {(it.get('topic') or '')[:60]}"
                          for it in nxt] if nxt else ["Nothing planned in the next 3 days."]
    kb = {"inline_keyboard": [[{"text": "💡 Pick a topic in demand", "callback_data": f"chp:{cid}"}],
                              [{"text": "⬅️ All channels", "callback_data": "chl:"}]]}
    return "\n".join(lines), kb


def pick_menu(cid: str, brain=None, log=print) -> tuple[str, dict]:
    """picker.suggest: topics with demand on YouTube NOW; each gets a [Make it] button (kept in state by number)."""
    from . import picker
    try:
        ideas = picker.suggest(cid, n=5, brain=brain, log=log)
    except Exception as e:  # noqa: BLE001 - the owner gets a plain answer, not silence
        return f"I couldn't look up topics right now ({type(e).__name__}). Try again in a few minutes.", {}
    if not ideas:
        return "No topic shows strong demand right now for this channel. Try again later today.", {}
    st = _load()
    st["pick"] = {"channel": cid, "ideas": [{"topic": i.get("topic", ""), "demand": i.get("demand", "")}
                                            for i in ideas[:5]]}
    _save(st)
    lines = ["💡 In demand now:"] + [f"{n}. {i.get('topic', '')[:80]}" + (f" ({i['demand'][:50]})" if i.get("demand")
                                                                            else "") for n, i in enumerate(ideas[:5], 1)]
    kb = {"inline_keyboard": [[{"text": f"✅ Make {n}", "callback_data": f"chm:{n - 1}"}]
                              for n in range(1, min(5, len(ideas)) + 1)]}
    return "\n".join(lines), kb


def pick_make(idx: int, log=print) -> str:
    """[Make n]: the picked topic goes onto the channel's next unmade slot (picker.pick_topic)."""
    from . import picker
    p = _load().get("pick") or {}
    ideas = p.get("ideas") or []
    if not (0 <= idx < len(ideas)):
        return "That list has expired: open 📺 Channels again."
    i = ideas[idx]
    return picker.pick_topic(i["topic"], p["channel"], demand=i.get("demand", ""), log=log)

HELP = ("👋 HookHouse, in short\n\n"
        "Fastest: tap 🎬 Studio (left of the message box) to watch, approve, change or reject every video in one place.\n\n"
        "Use the buttons at the bottom:\n"
        "📋 My tasks: what is left for you, and what is approved and coming\n"
        "📥 Waiting for me: videos and books that need your OK\n"
        "📊 Today: what was made, posted and planned today\n"
        "💰 Campaigns: pick paid clipping campaigns\n"
        "📈 Numbers: views and subscribers per channel\n"
        "🛠️ Anything broken?: a live check of the whole system\n\n"
        "On every video: ✅ Approve · ✏️ Change (then type what to fix) · ❌ Reject. Nothing is posted without your ✅.\n\n"
        "Campaigns in 3 steps: 1) tick the numbers you want  2) press Confirm  3) open each Join button I send and "
        "press Join Campaign. I find the footage and make the clips by myself.\n\n"
        "If something stops working, I tell you here with ⚠️ and what to do. More commands: /more")

MORE = ("Extra commands (you rarely need these):\n"
        "/approveall: approve every video you were already shown\n"
        "/source <link>: give me campaign footage (Google Drive / Dropbox link)\n"
        "/review [channel]: the end-of-day review (good, bad, weak points, what viewers said, lessons)\n"
        "/heal: problems and improvements waiting for 'Heal and Improve the system'\n"
        "/books: our Amazon books · /dashboard: the full monitoring page · /todo: setup list\n"
        "/doctor: check every account connection · /voice: Hindi narrator · /songs: Bloop songs\n"
        "/outreach, /trial, /email: creator outreach · /reply <number> <words>: answer a viewer comment")


def tasks_text() -> str:
    """📋 My tasks (owner 17 Nov: "a command that tells me the remaining and approved tasks")."""
    from datetime import timedelta
    from . import autopilot, books, db, todo
    now = autopilot._now()
    lines = ["📋 Your tasks", ""]
    # 1) what only the owner can do
    you = []
    try:
        waiting = [it for _, it in autopilot.items(0, 3) if it["status"] == "made" and autopilot._when(it) > now]
    except Exception:  # noqa: BLE001
        waiting = []
    if waiting:
        you.append(f"Approve {len(waiting)} video(s): tap 📥 Waiting for me")
    try:
        picked = db.list_campaigns(db.connect(), "picked")
    except Exception:  # noqa: BLE001
        picked = []
    for c in [c for c in picked if joinable(c)][:6]:
        you.append(f"Join campaign: {c.get('name', '')[:45]} ({c.get('url')})")
    try:
        bk = books.load()
        ready = [b.get("title", pid)[:40] for pid, b in bk.items() if b.get("status") == "ready"]
        if ready:
            you.append(f"Books ready to publish ({len(ready)}): {', '.join(ready[:3])}")
    except Exception as _swallowed:  # noqa: BLE001
        noted("telegram_bot.py:662", _swallowed)
        pass
    try:
        for t in [t for t in todo.items() if not t["done"]][:8]:
            you.append(f"{t.get('platform', '')}: {t['task'][:110]}")
    except Exception as _swallowed:  # noqa: BLE001
        noted("telegram_bot.py:667", _swallowed)
        pass
    lines.append("👉 For you:")
    lines += [f"{i}. {x}" for i, x in enumerate(you, 1)] or ["Nothing right now ✅"]
    # 2) approved and coming
    try:
        soon = sorted((it for _, it in autopilot.items(0, 7) if it["status"] in ("approved", "scheduled")
                       and autopilot._when(it) > now), key=autopilot._when)
    except Exception:  # noqa: BLE001
        soon = []
    lines += ["", f"✅ Approved, posting soon ({len(soon)}):"]
    lines += [f"• {autopilot._when(it):%a %d %b %H:%M} · {it.get('channel_name')} {it.get('kind')}"
              + (" (on YouTube, scheduled)" if it.get("youtube_id") else "") for it in soon[:12]] or ["none"]
    # 3) done in the last 24 hours
    try:
        done = [it for _, it in autopilot.items(2, 0) if it["status"] == "posted"
                and now - timedelta(hours=24) <= autopilot._when(it) <= now]
    except Exception:  # noqa: BLE001
        done = []
    if done:
        lines += ["", f"✔️ Posted in the last 24 h: {len(done)}"]
        lines += [f"• {it.get('channel_name')} {it.get('kind')}" for it in done[:8]]
    # 4) what the system does next by itself
    try:
        making = [it for _, it in autopilot.items(0, 2) if it["status"] in ("planned", "failed", "redo", "making")]
        lines += ["", f"🤖 I'm making next (no action needed): {len(making)} video(s) in the next 2 days"]
    except Exception as _swallowed:  # noqa: BLE001
        noted("telegram_bot.py:693", _swallowed)
        pass
    return "\n".join(lines)[:4000]


def health_text(store=None) -> str:
    """🛠️ Anything broken?: the watchdog's live check in plain words."""
    from . import watchdog
    try:
        if store is None:
            from .cloud.store import Store
            store = Store()
    except Exception:  # noqa: BLE001
        store = None
    found = watchdog.problems(store)
    held = ""
    try:
        from .autopilot import gate_held
        g = gate_held()
        if g:
            held = (f"\n\n🛑 {len(g)} video(s) held back by the campaign/reach checks (they only come to you when "
                    "every condition is met):\n" + "\n".join(
                        f"• {v.get('channel', '')}: {'; '.join(v.get('problems') or [])[:160]}"
                        for v in list(g.values())[:5]))
    except Exception as _swallowed:  # noqa: BLE001 - the health answer never fails because of this extra
        noted("telegram_bot.py:717", _swallowed)
        pass
    try:                                           # 18 Nov: problems that need a code fix / improvements
        from . import heal
        hi, imp = heal.open_items("high"), heal.open_items("improve")
        if hi:
            held += (f"\n\n🚨 {len(hi)} problem(s) need a code fix. Tell Claude on the PC: Heal and Improve the system\n"
                     + "\n".join(f"• {it['area']}: {it['error'][:120]} ({it['n']}x)" for _, it in hi[:4]))
        if imp:
            held += f"\n\n💡 {len(imp)} improvement(s) from the daily review are queued for the next 'Heal and Improve'."
    except Exception as _swallowed:  # noqa: BLE001
        noted("telegram_bot.py:727", _swallowed)
        pass
    if not found:
        return "✅ Everything is working: cloud, PC helper, Chrome, video making and campaigns." + held
    return "🛠️ What needs attention:\n\n" + "\n\n".join(f"• {t}" for t in found.values()) + held


def join_keyboard(ids: list[str], conn=None) -> dict | None:
    """After Confirm: one big button per campaign that opens its page (step 3: press Join Campaign there)."""
    from . import db
    conn = conn or db.connect()
    rows = []
    for cid in ids:
        c = db.get_campaign(conn, cid) or {}
        if c.get("url"):
            rows.append([{"text": f"🔗 Join: {(c.get('brand') or c.get('name') or cid)[:40]}", "url": c["url"]}])
    return {"inline_keyboard": rows} if rows else None


# ---------------- pairing ----------------
def new_pair_code() -> str:
    code = f"{secrets.randbelow(10**6):06d}"
    PAIR.parent.mkdir(parents=True, exist_ok=True)
    PAIR.write_text(code, encoding="utf-8")
    return code


def _set_env(key: str, value: str) -> None:
    env = ROOT / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    out, done = [], False
    for ln in lines:
        if ln.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{key}={value}")
    env.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value


def _try_pair(chat: str, text: str) -> bool:
    if not PAIR.exists():
        return False
    code = PAIR.read_text(encoding="utf-8").strip()
    if code and text.replace("/pair", "").strip() == code:
        _set_env("TELEGRAM_CHAT_ID", chat)
        PAIR.unlink()
        send("✅ Paired. This chat now controls HookHouse.\n\n" + HELP, chat=chat)
        return True
    return False


# ---------------- listener ----------------
def handle(update: dict, conn=None) -> None:
    owner = _chat()
    if "message" in update:
        msg = update["message"]
        chat, text = str(msg["chat"]["id"]), (msg.get("text") or "").strip()
        if not owner:
            _try_pair(chat, text)
            return
        if chat != owner:
            return                                            # only the owner's chat is answered
        if text in MENU:                                     # a tap on the bottom menu
            text = MENU[text]
        cmd = text.split()[0].lower() if text else ""
        waiting = _load().get("awaiting_change")
        if isinstance(waiting, str):                         # older format without a time
            waiting = {"tok": waiting, "at": time.time()}
        if waiting and time.time() - waiting.get("at", 0) > CHANGE_WAIT_S:
            st = _load()
            st.pop("awaiting_change", None)
            _save(st)
            waiting = None
        if waiting and text and not text.startswith("/"):
            from . import autopilot
            st = _load()
            st.pop("awaiting_change", None)
            _save(st)
            try:
                if waiting.get("book"):                       # ✏️ Change on a book
                    from . import books
                    reply = books.change_text(waiting["book"], text)
                else:
                    reply = autopilot.decide(waiting["tok"], "change", text)
            except Exception as e:  # noqa: BLE001
                reply = f"⚠️ Something went wrong saving that change ({type(e).__name__}). Tap Change again, please."
            if reply:
                send(reply)
            return
        if cmd in ("/start", "/help", "/menu"):
            send(HELP, reply_markup=MENU_KB)
        elif cmd == "/more":
            send(MORE, reply_markup=MENU_KB)
        elif cmd == "/health":
            send(health_text())
        elif cmd in ("/tasks", "/task", "/todo_all"):
            send(tasks_text())
        elif cmd == "/campaigns":
            digest(conn, fresh_only=False)
        elif cmd == "/status":
            send(status_text())
        elif cmd == "/voice":
            send_voices()
        elif cmd == "/channels":
            send(channels_text())
        elif cmd == "/pickmenu":                           # P2b Telegram 2.0: 📺 Channels -> one channel -> Pick
            send("📺 Which channel?", reply_markup=channel_list_kb())
        elif cmd == "/review":
            from . import daily_review
            send(daily_review.telegram_text(text[len("/review"):].strip() or None))
        elif cmd == "/heal":
            from . import heal
            send(heal.brief()[:3900])
        elif cmd == "/dashboard":
            send_dashboard()
        elif cmd == "/source":
            source_start(text[len("/source"):].strip())
        elif cmd == "/queue":
            send_queue()
        elif cmd == "/todo":
            from . import todo
            body, kb = todo.telegram_text()
            send(body, reply_markup=kb)
        elif cmd == "/songs":
            send_songs()
        elif cmd == "/books":
            from . import books
            send(books.text())
        elif cmd == "/doctor":
            from . import doctor
            send(doctor.text(doctor.run()))
        elif cmd == "/outreach":
            from . import outreach
            send(outreach.summary())
        elif cmd == "/approveall":
            from . import autopilot
            send(autopilot.approve_all_shown())
        elif cmd == "/email":
            from . import outreach
            parts = text.split()
            send(outreach.set_email(parts[1], parts[2]) if len(parts) >= 3 else
                 "Send it like this: /email <prospect> name@their-business.com  (from the creator's own website)")
        elif cmd == "/reply":
            from . import comments
            parts = text.split(maxsplit=2)
            send(comments.reply(int(parts[1]), parts[2]) if len(parts) == 3 and parts[1].isdigit() else
                 "Send it like this: /reply <number> your words  (the number is in the comment message)")
        elif cmd == "/trial":
            from . import outreach
            parts = text.split()
            send(outreach.start_trial(parts[1], parts[2]) if len(parts) >= 3 else
                 "Send it like this: /trial <prospect> <file link>  (the creator's Google Drive / Dropbox file)")
        elif text.startswith("/"):
            send("I don't know that command.\n\n" + HELP)
        elif text:
            send(note_owner_text(text))
        return
    cb = update.get("callback_query")
    if not cb or str(cb["message"]["chat"]["id"]) != owner:
        return
    data, s = cb.get("data", ""), _load()
    if data == "noop":                                         # an already-decided label
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Already done ✅")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:893", _swallowed)
            pass
        return
    if data.startswith(("chl:", "chn:", "chp:", "chm:")):     # P2b Telegram 2.0: channel menu + Pick
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"],
                text="Looking up topics in demand…" if data.startswith("chp:") else "")
        except Exception as _swallowed:  # noqa: BLE001 - the answer below still goes out
            noted("telegram_bot.py:channel_menu_ack", _swallowed)
        if data.startswith("chl:"):
            send("📺 Which channel?", reply_markup=channel_list_kb())
        elif data.startswith("chn:"):
            text_, kb = channel_menu(data[4:])
            send(text_, reply_markup=kb)
        elif data.startswith("chp:"):
            text_, kb = pick_menu(data[4:])
            send(text_, reply_markup=kb) if kb else send(text_)
        else:
            send(pick_make(int(data[4:]) if data[4:].isdigit() else -1))
        return
    if data == "aa:all":                                       # approve every video already shown
        from . import autopilot
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Working on it…")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:900", _swallowed)
            pass
        try:
            send(autopilot.approve_all_shown())
        except Exception as e:  # noqa: BLE001
            send(f"⚠️ That didn't work ({str(e)[:150]}). Nothing new was posted.")
        return
    if data[:3] in ("ap:", "rj:", "ch:"):                      # approvals from the autopilot
        from . import autopilot
        tok = data[3:]
        try:                                                   # answer the tap at once (uploads can take minutes)
            api("answerCallbackQuery", callback_query_id=cb["id"],
                text="Working on it…" if data.startswith("ap:") else "")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:913", _swallowed)
            pass
        if data.startswith("ch:"):
            s["awaiting_change"] = {"tok": tok, "at": time.time()}
            _save(s)
            if os.environ.get("HOOKHOUSE_CLOUD"):             # 20 Nov: the Worker already asked at the tap
                return
            send("✏️ What should I change? Type it in one message, for example: \"make the hook scarier\", "
                 "\"use a different first picture\". Only the title? Type \"title 2\" or \"title: your words\" (no remake needed).",
                 reply_markup={"force_reply": True})
            return
        try:
            reply = autopilot.decide(tok, "approve" if data.startswith("ap:") else "reject")
        except Exception as e:  # noqa: BLE001 - the owner always gets an answer
            reply = (f"⚠️ That didn't work ({type(e).__name__}: {str(e)[:150]}). Nothing was posted. "
                     "Try again in a few minutes.")
        if reply and reply.startswith(("✅", "❌")):
            try:
                iid = autopilot.item_of(tok)
                if iid:
                    autopilot.close_buttons(iid, reply.split("\n")[0])
            except Exception as _swallowed:  # noqa: BLE001
                noted("telegram_bot.py:934", _swallowed)
                pass
        if reply:
            send(reply)
        return
    if data.startswith("bk:"):                                 # book: ✅ Approve / ✏️ Change / ❌ Reject
        from . import books
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Got it")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:943", _swallowed)
            pass
        if data.startswith("bk:ch:"):
            s["awaiting_change"] = {"book": data[6:], "tok": "", "at": time.time()}
            _save(s)
            send("✏️ What should I change in the book? Type it in one message, for example: \"bigger pictures\", "
                 "\"new cover colour\", \"add a name page\".", reply_markup={"force_reply": True})
            return
        try:
            send(books.on_tap(data))
        except Exception as e:  # noqa: BLE001 - the owner always gets an answer
            send(f"⚠️ That didn't work ({type(e).__name__}: {str(e)[:150]}). Nothing was published. Tap again later.")
        return
    if data.startswith("td:"):                                 # to-do checkbox: tick it, show the list again
        from . import todo
        t = todo.tick(data[3:], True)
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="☑ Done!" if t else "Not found")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:961", _swallowed)
            pass
        body, kb = todo.telegram_text()
        try:
            api("editMessageText", chat_id=owner, message_id=cb["message"]["message_id"], text=body, reply_markup=kb)
        except Exception:  # noqa: BLE001 - message too old: send a fresh one
            send(body, reply_markup=kb)
        return
    if data.startswith("o:"):                                  # creator outreach buttons
        from . import outreach
        _, act, pid = (data.split(":", 2) + ["", ""])[:3]
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Saved")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:974", _swallowed)
            pass
        send(outreach.decide(act, pid))
        return
    if data[:3] in ("cr:", "cs:") and data[3:].isdigit():      # viewer comment: post the reply / skip it
        from . import comments
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Working on it…")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:982", _swallowed)
            pass
        try:
            send(comments.reply(int(data[3:])) if data.startswith("cr:") else comments.skip(int(data[3:])))
        except Exception as e:  # noqa: BLE001
            send(f"⚠️ That reply didn't go out ({str(e)[:150]}).")
        return
    if data.startswith("sp:"):                                 # winners share pack: owner posted it on a platform
        from . import share_packs
        _, item, plat = (data.split(":", 2) + ["", ""])[:3]
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text=share_packs.mark_posted(item, plat)[:180])
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:994", _swallowed)
            pass
        return
    if data.startswith("s:"):                                  # /source: which campaign the footage belongs to
        source_pick(data[2:])
        try:
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Saved")
        except Exception as _swallowed:  # noqa: BLE001
            noted("telegram_bot.py:1001", _swallowed)
            pass
        return
    d = s.get("digest") or {}
    note = ""
    if data.startswith("t:") and d:
        i = int(data[2:])
        picked = set(d.get("picked", []))
        picked.symmetric_difference_update({i})
        d["picked"] = sorted(picked)
        api("editMessageReplyMarkup", chat_id=owner, message_id=cb["message"]["message_id"],
            reply_markup=_keyboard(len(d["ids"]), picked))
    elif data == "a" and d:
        from . import db
        conn = conn or db.connect()
        d["picked"] = [i for i, cid in enumerate(d["ids"]) if (db.get_campaign(conn, cid) or {}).get("fit") == "OK"]
        api("editMessageReplyMarkup", chat_id=owner, message_id=cb["message"]["message_id"],
            reply_markup=_keyboard(len(d["ids"]), set(d["picked"])))
    elif data == "c" and (d or s.get("digests")):
        ids_all = (s.get("digests") or {}).get(str(cb["message"]["message_id"])) or d.get("ids", [])
        ticked = ticked_in(cb["message"].get("reply_markup"))   # the Worker flips the boxes on the message itself
        picks = ticked if ticked is not None else d.get("picked", [])
        ids = [ids_all[i] for i in picks if i < len(ids_all)]
        reply = confirm(ids, conn)
        send(reply)                                             # 20 Nov: the system joins; no manual links
        d["picked"] = []
        note = "Saved"
    elif data == "r":
        digest(conn, fresh_only=False)
        s = _load()
        d = s.get("digest") or {}
    elif data.startswith("v:"):
        save_choice("hindi_voice", data[2:])
        send(f"✅ Hindi voice {data[2:]} saved. New Hindi videos will use it.")
        note = "Saved"
    s["digest"] = d
    _save(s)
    try:
        api("answerCallbackQuery", callback_query_id=cb["id"], text=note)
    except Exception as _swallowed:  # noqa: BLE001 - old buttons can expire
        noted("telegram_bot.py:1040", _swallowed)
        pass


LOG_FILE = ROOT / "data" / "telegram" / "bot.log"
LOG_MAX = 5 * 1024 * 1024
_LOG_LOCK = __import__("threading").Lock()
_INSTANCE: list = []


def file_log(msg) -> None:
    """Time-stamped log in data/telegram/bot.log (kept under 5 MB: the old part moves to bot.old.log)."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _LOG_LOCK:
        try:
            if sys.stdout and sys.stdout.isatty():            # console window; the file below is the real log
                print(line, flush=True)
        except Exception as _swallowed:  # noqa: BLE001 - no console
            noted("telegram_bot.py:1057", _swallowed)
            pass
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX:
                LOG_FILE.replace(LOG_FILE.with_name("bot.old.log"))
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def single_instance(port: int = 47613) -> bool:
    """Only one bot may run: two would make and post everything twice. A local port works as the lock and is freed
    automatically when the process ends (even after a crash)."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):                 # Windows: nobody else may share the port
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        return False
    _INSTANCE.append(sock)
    return True


def run(log=None) -> None:
    log = log or file_log
    _token()
    if not single_instance():
        log("Another HookHouse bot is already running on this PC, so this one stops (no double posting).")
        sys.exit(3)
    log("Telegram bot listening… (Ctrl+C to stop)")
    import threading

    from . import autopilot
    def start_autopilot():
        t = threading.Thread(target=autopilot.loop, args=(autopilot.default_brain, log), daemon=True)
        t.start()
        return t
    pilot = start_autopilot()
    log("Autopilot started: makes videos ahead, asks you here, posts what you approve.")
    s = _load()
    offset = s.get("offset", 0)
    while True:
        if not pilot.is_alive():                                 # watchdog: the autopilot must always run
            log("Autopilot had stopped; starting it again.")
            pilot = start_autopilot()
        try:
            ups = api("getUpdates", http_timeout=70, offset=offset, timeout=50,
                      allowed_updates=["message", "callback_query"])
        except requests.RequestException as e:                   # network blips: wait and retry
            log(f"network: {e}")
            time.sleep(10)
            continue
        except Exception as e:  # noqa: BLE001 - never let the listener die (it would stop a render in progress)
            log(f"{type(e).__name__}: {e}")
            time.sleep(30)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            try:
                handle(u)
            except Exception as e:  # noqa: BLE001 - one bad update must not stop the bot
                log(f"update {u.get('update_id')}: {e}")
        s = _load()
        s["offset"] = offset
        _save(s)
