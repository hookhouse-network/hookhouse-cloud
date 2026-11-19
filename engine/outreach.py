"""Creator outreach on the phone (owner, 12 Nov 2026: "reach out to different content creators for clipping their
videos initially for free then charge"). Built on the pitch kit (engine/pitch.py):

1. Every Monday the bot sends up to 5 prospects (creators who already pay clippers come first), each with a ready,
   honest email. The owner sends it from the HookHouse Gmail (never a personal address) and taps "Sent".
2. Day 3 and day 7: the follow-up text comes back with "Sent follow-up / They replied / Stop" buttons.
3. They say yes to the free trial: `/trial <prospect> <file link>` records their written permission (the register in
   config/clip_sources.yaml + data/permissions/) and sends the footage to Hot Take HQ's clip pipeline. Every clip
   still needs the owner's approval; the owner shares the posted links with the creator.
4. After 7 days: ask for feedback and offer the Starter plan ($500/month). "They're a client" or "Lost".
Sending (13 Nov): with the HookHouse Gmail connected (send-only) and POSTAL_ADDRESS in .env, the owner taps
"📧 Send for me" and the system sends the pitch / follow-up itself (engine/gmail.py: daily cap, opt-out list, the
address + opt-out line US business-email rules ask for). Nothing is sent without that tap. The creator's address
is never collected automatically: the owner adds it with /email <prospect> <address> from the creator's own
website or About page.
"""
from __future__ import annotations

import time

import yaml

from . import pitch
from .config import ROOT

REGISTER = ROOT / "config" / "clip_sources.yaml"
PERMISSIONS = ROOT / "data" / "permissions"
WEEKLY = 5


def _sections(md: str) -> dict[str, str]:
    out, cur = {}, None
    for ln in md.splitlines():
        if ln.startswith("## "):
            cur = ln[3:].strip().lower()
            out[cur] = ""
        elif cur:
            out[cur] += ln + "\n"
    return {k: v.strip() for k, v in out.items()}


def _cols(conn) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(prospects)")}
    for col in ("email", "thread_id", "message_id", "subject"):
        if col not in have:
            conn.execute(f"ALTER TABLE prospects ADD COLUMN {col} TEXT")
    conn.commit()


def split_email(text: str) -> tuple[str, str]:
    """'**Subject:** ...' line + body (the pitch file's Email section)."""
    lines = str(text or "").strip().splitlines()
    subject = ""
    if lines and lines[0].lower().lstrip("*").startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip(" *")
        lines = lines[1:]
    return subject, "\n".join(lines).strip()


def set_email(pid: str, addr: str) -> str:
    """/email <prospect> <address>: the creator's business address, copied from their own website or About page."""
    from . import gmail
    conn = pitch.connect()
    _cols(conn)
    row = conn.execute("SELECT name FROM prospects WHERE id=?", (pid,)).fetchone()
    if not row:
        return f"No prospect called '{pid}'. Send /outreach to see the list."
    if not gmail.valid(addr):
        return "That doesn't look like an email address. Example: /email big-podcast hello@bigpodcast.com"
    conn.execute("UPDATE prospects SET email=? WHERE id=?", (addr.strip(), pid))
    conn.commit()
    ok, why = gmail.ready()
    return (f"Saved {row[0]}'s address." + (" Tap \"📧 Send for me\" on their pitch (send /outreach to see it again)."
                                            if ok else f" To let me send it myself: {why}."))


def send_for_me(pid: str, kind: str = "pitch") -> str:
    """The owner's tap: send the pitch or the next follow-up from the HookHouse Gmail."""
    from . import gmail
    conn = pitch.connect()
    _cols(conn)
    row = conn.execute("SELECT name, email, thread_id, message_id, subject FROM prospects WHERE id=?", (pid,)).fetchone()
    if not row:
        return "I can't find that prospect any more."
    name, email, thread_id, message_id, subject = row
    if not email:
        return f"I need {name}'s address first: /email {pid} name@their-business.com (from their website)."
    t = pitch_text(pid, conn)
    if kind == "pitch":
        subject, body = split_email(t["email"])
        thread = None
    else:
        from . import telegram_bot as tb
        k = int(tb._load().get("outreach_round", {}).get(pid, 1))
        body = t.get("follow_up_1" if k == 1 else "follow_up_2", "")
        thread = {"thread_id": thread_id, "message_id": message_id}
    try:
        res = gmail.send(email, subject or f"Clips for {name}", body, thread)
    except Exception as e:  # noqa: BLE001 - tell the owner, nothing changes
        return f"Not sent: {e}"
    if kind == "pitch":
        conn.execute("UPDATE prospects SET thread_id=?, message_id=?, subject=? WHERE id=?",
                     (res["thread_id"], res["message_id"], subject, pid))
        conn.commit()
        return decide("s", pid).replace("Noted: pitched", "📧 Sent from the HookHouse Gmail to")
    return "📧 Follow-up sent. " + decide("f", pid)


def _send_buttons(pid: str, kind: str) -> list[tuple[str, str]]:
    from . import gmail
    if not gmail.ready()[0]:
        return []
    return [("📧 Send for me", "m" if kind == "pitch" else "fm")]


def pitch_text(pid: str, conn=None, brain=None) -> dict[str, str]:
    """email (subject + body), dm, follow_up_1, follow_up_2 for a prospect (writes the pitch the first time)."""
    conn = conn or pitch.connect()
    path = pitch.PITCHES / f"{pid}.md"
    if not path.exists():
        pitch.make_pitch(conn, pid, brain=brain)
    sec = _sections(path.read_text(encoding="utf-8"))
    return {"email": sec.get("email", ""), "dm": sec.get("short dm (instagram / x)", ""),
            "follow_up_1": sec.get("follow-up (day 3)", ""), "follow_up_2": sec.get("follow-up (day 7)", "")}


def _buttons(pid: str, *pairs: tuple[str, str]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": f"o:{a}:{pid}"[:64]} for t, a in pairs]]}


def weekly_queue(brain=None, log=print, n: int = WEEKLY) -> int:
    """Monday: new prospects with a ready email, one message each."""
    from . import telegram_bot as tb
    conn = pitch.connect()
    pitch.import_from_campaigns(conn)
    st = tb._load()
    offered = st.setdefault("outreach_offered", {})
    rows = conn.execute("SELECT id, name, notes FROM prospects WHERE status='new' ORDER BY "
                        "CASE WHEN source='runs a clipping campaign' THEN 0 ELSE 1 END, created").fetchall()
    sent = 0
    for pid, name, notes in rows:
        if pid in offered or sent >= n:
            continue
        try:
            t = pitch_text(pid, conn, brain)
        except Exception as e:  # noqa: BLE001 - no writer today: try next week
            log(f"outreach {pid}: {e}")
            continue
        from . import gmail
        how = ("Tap 📧 to send it from the HookHouse Gmail, or copy it" if gmail.ready()[0] else
               "Send this from the HookHouse Gmail")
        tb.send(f"📨 Pitch {sent + 1}/{n}: {name}\nWhy: {str(notes)[:160]}\n\n{how} (add their address with "
                f"/email {pid} name@their-business.com, from their own website):\n\n{t['email'][:3000]}"
                f"{gmail.footer()}",
                reply_markup=_buttons(pid, *_send_buttons(pid, "pitch"), ("✅ I sent it", "s"), ("⏭ Later", "l"),
                                      ("❌ Not a fit", "x")))
        offered[pid] = time.time()
        sent += 1
    tb._save(st)
    return sent


def followups(log=print) -> int:
    """Daily: follow-ups that are due (pitched: day 3 / day 7; trial: ask for feedback and offer the plan)."""
    from . import telegram_bot as tb
    conn = pitch.connect()
    st = tb._load()
    done = st.setdefault("outreach_followed", {})
    n = 0
    for pid, name, status, _due in pitch.pipeline(conn)["due"]:
        key = f"{pid}:{status}:{int(_due // 86400)}"
        if key in done:
            continue
        if status == "pitched":
            k = int(st.get("outreach_round", {}).get(pid, 1))
            text = pitch_text(pid, conn).get("follow_up_1" if k == 1 else "follow_up_2", "")
            tb.send(f"🔁 Follow-up for {name} (send it as a reply to your first email):\n\n{text}",
                    reply_markup=_buttons(pid, *_send_buttons(pid, "follow"), ("✅ Sent follow-up", "f"),
                                          ("💬 They replied", "r"), ("❌ Stop", "x")))
        elif status == "trial":
            tb.send(f"⭐ {name}'s free trial week is over. Send them the clip links with the views, ask what they think, "
                    "and offer the Starter plan ($500/month for 12 clips, or Growth $1,000 for 24).",
                    reply_markup=_buttons(pid, ("🎉 They're a client", "c"), ("⏳ Later", "l"), ("❌ Lost", "x")))
        elif status == "replied":
            tb.send(f"💬 {name} replied: offer the free trial. Ask for one long video FILE link (Google Drive or "
                    f"Dropbox) and their written OK that we may clip and post it. Then send:\n/trial {pid} <link>")
        else:
            continue
        done[key] = time.time()
        n += 1
    tb._save(st)
    return n


def decide(action: str, pid: str) -> str:
    """Owner's tap on an outreach button."""
    from . import telegram_bot as tb
    conn = pitch.connect()
    row = conn.execute("SELECT name, status FROM prospects WHERE id=?", (pid,)).fetchone()
    if not row:
        return "I can't find that prospect any more."
    name, status = row
    if action == "s":
        pitch.set_status(conn, pid, "pitched")
        return f"Noted: pitched {name}. I'll bring the follow-up in 3 days."
    if action == "f":
        st = tb._load()
        rnd = st.setdefault("outreach_round", {})
        rnd[pid] = int(rnd.get(pid, 1)) + 1
        tb._save(st)
        if rnd[pid] > 2:
            pitch.set_status(conn, pid, "lost")
            return f"Two follow-ups sent to {name}. I'll stop here (no spam)."
        pitch.set_status(conn, pid, "pitched")
        return f"Noted. Last follow-up for {name} in 3-4 days."
    if action == "r":
        pitch.set_status(conn, pid, "replied")
        return (f"🎉 {name} replied! Offer the free trial: ask for one long video FILE link and their written OK. "
                f"Then send: /trial {pid} <link>")
    if action == "c":
        pitch.set_status(conn, pid, "client")
        return f"💰 {name} is a client! Agree the plan in writing (clips per month, price, where they're posted)."
    if action == "m":
        return send_for_me(pid, "pitch")
    if action == "fm":
        return send_for_me(pid, "follow")
    if action == "x":
        pitch.set_status(conn, pid, "lost")
        _cols(conn)
        email = (conn.execute("SELECT email FROM prospects WHERE id=?", (pid,)).fetchone() or [None])[0]
        if email:                                              # never email them again
            from . import gmail
            gmail.opt_out(email)
        return f"OK, {name} is closed (never emailed again)."
    if action == "l":
        st = tb._load()
        st.setdefault("outreach_offered", {}).pop(pid, None)
        tb._save(st)
        return f"OK, {name} comes back next week."
    return "Unknown action."


def start_trial(pid: str, link: str, evidence: str = "") -> str:
    """Free trial: record the creator's written permission and send their footage to Hot Take HQ's clip pipeline."""
    from .clips import PLATFORM_LINKS
    if not link.startswith(("http://", "https://")) or PLATFORM_LINKS.search(link):
        return ("Send the creator's FILE link (Google Drive / Dropbox / direct .mp4), not a YouTube/Twitch page: "
                f"/trial {pid} https://drive.google.com/file/d/...")
    conn = pitch.connect()
    row = conn.execute("SELECT name, url FROM prospects WHERE id=?", (pid,)).fetchone()
    if not row:
        return f"No prospect called '{pid}'. Send /outreach to see the list."
    name, url = row
    PERMISSIONS.mkdir(parents=True, exist_ok=True)
    note = PERMISSIONS / f"{pid}_{time.strftime('%Y-%m-%d')}.txt"
    note.write_text(f"{name} agreed in writing (email reply, confirmed by the owner in Telegram on "
                    f"{time.strftime('%Y-%m-%d %H:%M')}) that HookHouse may clip and post: {link}\n{evidence}\n"
                    "Keep the email itself in the HookHouse Gmail.", encoding="utf-8")
    entries = yaml.safe_load(REGISTER.read_text(encoding="utf-8")) or [] if REGISTER.exists() else []
    if not any(isinstance(e, dict) and e.get("match") == link for e in entries):
        block = (f"\n- match: \"{link}\"\n  basis: written_permission\n  owner: \"{name}\"\n"
                 f"  evidence: \"{note.relative_to(ROOT).as_posix()}\"\n  credit: \"Clip from {name} (used with permission)\"\n"
                 f"  may_monetize: false\n  notes: \"free trial (outreach), {time.strftime('%Y-%m-%d')}\"\n")
        with REGISTER.open("a", encoding="utf-8") as f:
            f.write(block)
    from . import weekly
    weekly.CLIP_SOURCES.parent.mkdir(parents=True, exist_ok=True)
    have = {s["source"] for s in weekly._read_sources()}
    if link not in have:
        with weekly.CLIP_SOURCES.open("a", encoding="utf-8") as f:
            f.write(f"{link} channel=hot_take_hq\n")
    pitch.set_status(conn, pid, "trial")
    return (f"🎬 Free trial started for {name}. Their footage goes to Hot Take HQ's next clip slots; you approve every "
            "clip as usual. Share the posted links with them; in 7 days I'll remind you to ask for feedback and offer "
            "the plan.")


def summary() -> str:
    conn = pitch.connect()
    p = pitch.pipeline(conn)
    c = p["counts"]
    return ("📨 Outreach: " + " · ".join(f"{k} {v}" for k, v in c.items()) +
            (f"\nDue now: {', '.join(n for _, n, _, _ in p['due'][:6])}" if p["due"] else "") +
            "\nNew pitches come every Monday. Free trial: /trial <name> <file link>")


