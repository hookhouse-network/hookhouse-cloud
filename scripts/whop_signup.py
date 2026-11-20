"""Whop account for campaign clipping (owner 20 Nov 2026: "account, do it as you suggest"; the owner taps legal-terms,
consent, KYC and payout screens). Content Rewards campaigns pay through Whop (INR bank payouts after Whop's KYC).

Headless HookHouse Chrome (port 9333). Email: the HookHouse Gmail alias hookhouse.network+whop@gmail.com (never the
owner's personal address); the one-time code is read from the HookHouse Gmail tab. The script STOPS (and says what
the owner must tap) at any terms / consent / identity / payout screen and at robot checks.

python -m scripts.whop_signup probe      read-only: what the login page shows (no clicks, no typing)
python -m scripts.whop_signup start      enter the alias, request the code, type it, stop before any consent"""
import asyncio
import json
import re
import sys
import time
import urllib.parse

from engine.config import ROOT, load_env
from engine.kick import _Tab

ALIAS = "hookhouse.network+whop@gmail.com"
ACCOUNT = ROOT / "data" / "secrets" / "whop_account.json"
LOGIN = "https://whop.com/login/"
CONSENT = re.compile(r"terms of (service|use)|privacy policy|i agree|accept|consent|verify your identity|kyc|"
                     r"date of birth|payout|bank account|tax", re.I)
ROBOT = re.compile(r"captcha|robot|verify you are human|challenge|cloudflare", re.I)


def say(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8"))
    sys.stdout.flush()


async def page_report(tab) -> dict:
    return await tab.js("""(() => {
      const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      return {url: location.href, title: document.title,
        text: (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 40),
        inputs: [...document.querySelectorAll('input')].filter(vis).map(i => [i.type, i.name, i.placeholder,
                 i.autocomplete]),
        buttons: [...document.querySelectorAll('button,a[role=button]')].filter(vis)
                 .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 25)};
    })()""") or {}


async def probe() -> None:
    async with _Tab(LOGIN) as tab:
        await asyncio.sleep(12)
        rep = await page_report(tab)
        say(json.dumps(rep, ensure_ascii=False, indent=1)[:3000])


async def gmail_code(since: float, wait_s: int = 240) -> str | None:
    """Newest Whop code mail of the last 15 minutes."""
    q = urllib.parse.quote("from:whop newer_than:15m")
    async with _Tab(f"https://mail.google.com/mail/u/0/#search/{q}") as gm:
        while time.time() - since < wait_s:
            await asyncio.sleep(10)
            body = await gm.js('(document.querySelector("[role=main]") || document.body).innerText') or ""
            codes = re.findall(r"\b(\d{6})\b", body)
            if codes:
                return codes[0]
            await gm.js("location.reload()")
    return None


async def start() -> None:
    load_env()
    async with _Tab(LOGIN) as tab:
        await asyncio.sleep(12)
        rep = await page_report(tab)
        text = " ".join(rep.get("text") or [])
        if ROBOT.search(text):
            say("ROBOT CHECK on the login page: the owner must open it (visible window)")
            return
        email = next((i for i in rep.get("inputs") or [] if i[0] == "email" or "email" in (i[1] or "").lower()
                      or "email" in (i[2] or "").lower()), None)
        if not email:
            say("no email field on the login page: " + json.dumps(rep, ensure_ascii=False)[:800])
            return
        ok = await tab.js(f"""(() => {{ const e = [...document.querySelectorAll('input')].find(i => i.type === 'email'
              || /email/i.test(i.name || '') || /email/i.test(i.placeholder || '')); if (!e) return false; e.focus();
              const p = Object.getPrototypeOf(e); Object.getOwnPropertyDescriptor(p, 'value').set.call(e, {json.dumps(ALIAS)});
              e.dispatchEvent(new Event('input', {{bubbles: true}})); return e.value === {json.dumps(ALIAS)}; }})()""")
        if not ok:
            say("could not type the email")
            return
        since = time.time()
        if not (await tab.click_text("Continue") or await tab.click_text("Continue with email")
                or await tab.click_text("Sign in") or await tab.click_text("Log in")):
            say("no Continue button after the email")
            return
        await asyncio.sleep(8)
        rep = await page_report(tab)
        text = " ".join(rep.get("text") or [])
        say("after email: " + " / ".join((rep.get("text") or [])[:12])[:500])
        if ROBOT.search(text):
            say("ROBOT CHECK after the email: the owner must open it (visible window)")
            return
        code = await gmail_code(since)
        if not code:
            say("no Whop code mail within 4 minutes")
            return
        await tab.cmd("Input.insertText", {"text": code})
        await asyncio.sleep(10)
        rep = await page_report(tab)
        text = " ".join(rep.get("text") or [])
        say("after code: " + " / ".join((rep.get("text") or [])[:15])[:700])
        ACCOUNT.parent.mkdir(parents=True, exist_ok=True)
        stop = bool(CONSENT.search(text))
        ACCOUNT.write_text(json.dumps({"email": ALIAS, "created": time.strftime("%Y-%m-%d %H:%M"), "url": rep.get("url"),
                                       "needs_owner": stop,
                                       "terms": "owner agreed to Whop's terms in chat on 20 Nov 2026 (Continue pressed "
                                                "for the owner)"}), encoding="utf-8")
        if stop:
            say("STOP: this screen asks for terms/consent/identity/payout: the owner taps it (visible window)")


if __name__ == "__main__":
    asyncio.run({"probe": probe, "start": start}[(sys.argv[1:] or ["probe"])[0]]())
