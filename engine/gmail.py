"""Creator outreach email, sent by the system after the owner's tap (owner, 12 Nov 2026: "replace all the manual
processes"). Before: copy each pitch into Gmail by hand. Now: tap "📧 Send for me" in Telegram.

- Only from the HookHouse Gmail (never a personal address), connected once with `python cli.py connect gmail`.
  The permission is SEND ONLY: the system can never read the mailbox.
- Every email ends with the studio's postal address and a one-line opt-out. Most creators we pitch are in the
  US, whose business-email rules (CAN-SPAM) ask for both. Without POSTAL_ADDRESS in .env nothing is sent
  automatically (the copy-and-send way keeps working).
- At most 10 emails a day; never again to an address that said no (data/state/outreach_optout.json).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from email.message import EmailMessage
from email.utils import make_msgid

import requests

from .config import ROOT
from .connect import GMAIL_TOKEN
from .publish import google_access_token
from engine.core.http import HTTP

SENT = ROOT / "data" / "state" / "gmail_sent.json"
OPTOUT = ROOT / "data" / "state" / "outreach_optout.json"
DAILY_MAX = 10
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _load(p) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(p, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")


def ready() -> tuple[bool, str]:
    """Can the system send by itself? (False + what is missing)"""
    if not GMAIL_TOKEN.exists():
        return False, "connect the HookHouse Gmail once: python cli.py connect gmail"
    if not os.environ.get("POSTAL_ADDRESS", "").strip():
        return False, "add POSTAL_ADDRESS to .env (a PO box or business address; US business-email rules ask for one)"
    return True, ""


def footer() -> str:
    addr = os.environ.get("POSTAL_ADDRESS", "").strip()
    return ("\n\n--\nHookHouse" + (f" · {addr}" if addr else "")
            + "\nNot interested? Reply \"no thanks\" and we won't email you again.")


def valid(addr: str) -> bool:
    return bool(EMAIL_RE.match(str(addr or "").strip()))


def opted_out(addr: str) -> bool:
    return str(addr or "").strip().lower() in _load(OPTOUT)


def opt_out(addr: str) -> None:
    if valid(addr):
        d = _load(OPTOUT)
        d[addr.strip().lower()] = time.time()
        _save(OPTOUT, d)


def sent_today() -> int:
    day = time.strftime("%Y-%m-%d")
    return sum(1 for r in _load(SENT).get("log", []) if r.get("day") == day)


def build(to: str, subject: str, body: str, thread: dict | None = None) -> tuple[EmailMessage, str]:
    msg = EmailMessage()
    msg["To"] = to.strip()
    subject = " ".join(str(subject or "Clips for your show").split())[:120]
    msg["Subject"] = f"Re: {subject}" if thread and not subject.lower().startswith("re:") else subject
    mid = make_msgid(domain="mail.gmail.com")             # no PC name inside the message id
    msg["Message-ID"] = mid
    if thread and thread.get("message_id"):                # follow-ups stay in the same conversation
        msg["In-Reply-To"] = thread["message_id"]
        msg["References"] = thread["message_id"]
    msg.set_content(str(body or "").strip() + footer())
    return msg, mid


def send(to: str, subject: str, body: str, thread: dict | None = None, session=HTTP) -> dict:
    """Send one email from the HookHouse Gmail. Returns {"id", "thread_id", "message_id", "subject"}."""
    ok, why = ready()
    if not ok:
        raise RuntimeError(why)
    if not valid(to):
        raise ValueError(f"not an email address: {to}")
    if opted_out(to):
        raise RuntimeError("they asked not to be emailed again")
    if sent_today() >= DAILY_MAX:
        raise RuntimeError(f"today's limit of {DAILY_MAX} emails is reached; tap again tomorrow")
    token = google_access_token(GMAIL_TOKEN, session)
    if not token:
        raise RuntimeError("the Gmail sign-in is missing; connect again: python cli.py connect gmail")
    msg, mid = build(to, subject, body, thread)
    payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread and thread.get("thread_id"):
        payload["threadId"] = thread["thread_id"]
    r = session.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                     headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=30)
    r.raise_for_status()
    d = r.json()
    st = _load(SENT)
    st.setdefault("log", []).append({"day": time.strftime("%Y-%m-%d"), "to_domain": to.split("@")[-1],
                                     "at": time.time()})
    st["log"] = st["log"][-500:]
    _save(SENT, st)
    return {"id": d.get("id", ""), "thread_id": d.get("threadId", ""), "message_id": mid, "subject": msg["Subject"]}
