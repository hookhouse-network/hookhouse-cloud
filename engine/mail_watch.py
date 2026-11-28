"""Mail watch (owner 28 Nov: "check the mail, we have received many restriction and failure mails" - they sat unread
for days). Once a day the PC reads the HookHouse Gmail INBOX LIST through the signed-in HookHouse Chrome (CDP 9333):
sender, subject and the preview line only. It never opens a message (nothing is marked read), never clicks, never
sends. New warning mails go to the owner in ONE Telegram message; each mail is reported once (data/state/mail_seen.json).

The Gmail API connection stays SEND ONLY (engine/gmail.py); reading happens only through the owner's own browser
session on the PC."""
from __future__ import annotations

import hashlib
import json
import re
import time

from .config import ROOT

SEEN = ROOT / "data" / "state" / "mail_seen.json"
STATE = ROOT / "data" / "state" / "mail_watch.txt"
WARN = re.compile(r"restrict|deactivat|suspend|disabled|banned|violat|policy|verify|confirm it.s you|action required|"
                  r"urgent|run failed|security alert|copyright|strike|claim|removed|terminated|limit .*reached",
                  re.I)
NOISE = re.compile(r"tips|how pinterest works|steps away|black friday|sale|join cloudflare|thanksgiving|"
                   r"you.re back on", re.I)
TRUSTED = ("facebook.com", "instagram.com", "github.com", "cloudflare.com", "pinterest.com", "google.com",
           "youtube.com", "tiktok.com", "threads.net", "dailymotion.com", "payhip.com", "gumroad.com", "rumble.com",
           "meta.com", "amazon.com")


def classify(rows: list[dict]) -> list[dict]:
    """The rows that are warnings worth the owner's attention (not promotions, not already-resolved notices)."""
    out = []
    for r in rows:
        subject, snippet, sender = r.get("subject", ""), r.get("snippet", ""), (r.get("from") or "").lower()
        text = f"{subject} {snippet}"
        if not WARN.search(text) or NOISE.search(subject):
            continue
        r = dict(r, trusted=any(sender.endswith(d) or f".{d}" in sender or f"@{d}" in sender for d in TRUSTED))
        out.append(r)
    return out


def _key(r: dict) -> str:
    return hashlib.sha1(f"{r.get('from')}|{r.get('subject')}|{r.get('date')}".encode("utf-8")).hexdigest()[:16]


def new_warnings(rows: list[dict], seen: set[str]) -> list[dict]:
    return [r for r in classify(rows) if _key(r) not in seen]


def message(warns: list[dict]) -> str:
    lines = [f"📬 {len(warns)} new warning email(s) in the HookHouse inbox:"]
    for r in warns[:10]:
        flag = "" if r.get("trusted") else " ⚠️ unknown sender (could be phishing: don't click links)"
        lines.append(f"• {r.get('name') or r.get('from')}: {r.get('subject', '')[:90]}{flag}")
    lines.append("Tell Claude 'check the mail' for what each needs; I never open or answer them by myself.")
    return "\n".join(lines)


def read_inbox(days: int = 2, port: int = 9333) -> list[dict]:
    """The inbox list (sender, subject, preview, date) of the last days. Read-only: no message is opened."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}").contexts[0]
        page = ctx.new_page()
        try:
            page.goto(f"https://mail.google.com/mail/u/0/#search/newer_than%3A{days}d", wait_until="domcontentloaded",
                      timeout=60000)
            page.wait_for_selector("tr.zA", timeout=30000)
            page.wait_for_timeout(1500)
            return page.evaluate("""() => Array.from(document.querySelectorAll('tr.zA')).slice(0, 80).map(r => ({
                from: (r.querySelector('.yW span[email]') || {getAttribute: () => ''}).getAttribute('email') || '',
                name: (r.querySelector('.yW') || {}).innerText || '',
                subject: (r.querySelector('.bog') || {}).innerText || '',
                snippet: (r.querySelector('.y2') || {}).innerText || '',
                date: (r.querySelector('.xW span') || {getAttribute: () => ''}).getAttribute('title') || ''}))""")
        finally:
            page.close()


def run(log=print, send=None, rows: list[dict] | None = None) -> int:
    """Once a day on the PC. Returns how many new warnings were reported."""
    today = time.strftime("%Y-%m-%d")
    if rows is None and STATE.exists() and STATE.read_text(encoding="utf-8").strip() == today:
        return 0
    try:
        seen = set(json.loads(SEEN.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    rows = rows if rows is not None else read_inbox()
    warns = new_warnings(rows, seen)
    if warns:
        if send is None:
            from .telegram_bot import notify as send
        send(message(warns))
        log(f"mail watch: {len(warns)} new warning email(s) reported")
    seen |= {_key(r) for r in classify(rows)}
    from .core.atomic import write_json
    write_json(SEEN, sorted(seen)[-2000:])
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(today, encoding="utf-8")
    return len(warns)
