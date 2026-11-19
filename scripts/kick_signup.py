"""Kick account for the clipping workflow (20 Nov 2026): Kick's clip Download button needs a signed-in viewer.

Headless HookHouse Chrome (port 9333). Email: the HookHouse Gmail alias hookhouse.network+kick@gmail.com; birthday and
password: IG_SIGNUP_BIRTHDATE / IG_SIGNUP_PASSWORD from .env (owner's own, never printed); newsletter box left
unticked; the confirmation code is read from the HookHouse Gmail tab. Stops and says so on a robot check.
python -m scripts.kick_signup [username ...]"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from engine.config import ROOT, load_env
from engine.kick import _Tab

ALIAS = "hookhouse.network+kick@gmail.com"
NAMES = ["hookhouseclips", "hookhouse_clips", "hookhouseclipper", "hookhouseclipsdaily"]
ACCOUNT = ROOT / "data" / "secrets" / "kick_account.json"

SET_JS = """((sel, val) => { const e = document.querySelector(sel); if (!e) return false; e.focus();
  const proto = Object.getPrototypeOf(e); Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, val);
  e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
  e.blur(); return e.value.length === val.length; })"""


def say(msg: str) -> None:
    sys.stdout.buffer.write((msg + "\n").encode("utf-8"))
    sys.stdout.flush()


async def fill(tab, sel: str, val: str) -> bool:
    return bool(await tab.js(f"{SET_JS}({json.dumps(sel)}, {json.dumps(val)})"))


async def form_text(tab) -> str:
    return await tab.js("((document.querySelector('input[name=password]') || document.body).closest('form') "
                        "|| document.querySelector('[role=dialog]') || document.body).innerText") or ""


async def gmail_code(since: float, wait_s: int = 240) -> str | None:
    """Newest Kick code mail of the last 15 minutes (sign-ups run one at a time)."""
    q = urllib.parse.quote("from:kick newer_than:15m")
    async with _Tab(f"https://mail.google.com/mail/u/0/#search/{q}") as gm:
        while time.time() - since < wait_s:
            await asyncio.sleep(10)
            body = await gm.js('(document.querySelector("[role=main]") || document.body).innerText') or ""
            m = re.search(r"(?:code|verif)[^\d]{0,80}(\d{6})|(\d{6})[^\d]{0,40}(?:code|verif)", body, re.I)
            if m:
                return m.group(1) or m.group(2)
            await gm.js("location.reload()")
    return None


async def main(names: list[str]) -> None:
    load_env()
    pw, born = os.environ.get("IG_SIGNUP_PASSWORD", ""), os.environ.get("IG_SIGNUP_BIRTHDATE", "").strip()
    if len(pw) < 8 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", born):
        say("IG_SIGNUP_PASSWORD (8+ characters) / IG_SIGNUP_BIRTHDATE (YYYY-MM-DD) missing in .env")
        return
    async with _Tab("https://kick.com/") as tab:
        await asyncio.sleep(12)
        await tab.click_text("Confirm My Choices")              # cookie banner: keep the defaults
        await asyncio.sleep(2)
        if not await tab.click_text("Sign Up"):
            say("no Sign Up button (already signed in?)")
            return
        await asyncio.sleep(5)
        ok = await fill(tab, "input[name=email]", ALIAS) and await fill(tab, "input[name=birthdate]", born)
        if not ok:
            say("could not fill email/birthday")
            return
        user = None
        for name in names:
            await fill(tab, "input[name=username]", name)
            await asyncio.sleep(3)
            txt = (await form_text(tab)).lower()
            if not re.search(r"taken|not available|already|invalid", txt):
                user = name
                break
            say(f"username {name}: not available")
        if not user:
            say("no free username: pass others as arguments")
            return
        await fill(tab, "input[name=password]", pw)
        await asyncio.sleep(2)
        errs = [x for x in (await form_text(tab)).splitlines() if re.search(r"must|invalid|required|taken", x, re.I)]
        if errs:
            say("form says: " + " / ".join(errs)[:300])
            return
        since = time.time()
        clicked = await tab.js("""(() => { const f = document.querySelector('input[name=password]').closest('form');
          const b = [...f.querySelectorAll('button[type=submit]')].find(x => (x.innerText || '').trim() === 'Sign Up');
          if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
        if not clicked:
            say("Sign Up button not found in the form")
            return
        for k in ("mouseMoved", "mousePressed", "mouseReleased"):
            await tab.cmd("Input.dispatchMouseEvent", {"type": k, "x": clicked[0], "y": clicked[1], "button": "left",
                                                       "clickCount": 1})
        await asyncio.sleep(8)
        txt = await tab.js("document.body.innerText") or ""
        if re.search(r"captcha|robot|verify you are human|challenge", txt, re.I):
            say("ROBOT CHECK shown: the owner must tick it (visible window)")
            return
        code_box = await tab.js("!!document.querySelector('input[autocomplete=one-time-code], input[name*=code], "
                                "input[inputmode=numeric]')")
        say(f"signed up as {user}; code box: {code_box}")
        if code_box:
            code = await gmail_code(since)
            if not code:
                say("no Kick code mail within 4 minutes")
                return
            await tab.js("""(() => { const e = document.querySelector('input[autocomplete=one-time-code], input[name*=code],
              input[inputmode=numeric]'); e.focus(); })()""")
            await tab.cmd("Input.insertText", {"text": code})
            await asyncio.sleep(3)
            await tab.click_text("Verify", "Confirm", "Submit", "Continue")
            await asyncio.sleep(8)
        signed = await tab.js("!document.body.innerText.includes('Log In')")
        ACCOUNT.parent.mkdir(parents=True, exist_ok=True)
        ACCOUNT.write_text(json.dumps({"username": user, "email": ALIAS, "created": time.strftime("%Y-%m-%d %H:%M"),
                                       "signed_in": bool(signed)}), encoding="utf-8")
        tail = [x for x in (await tab.js("document.body.innerText") or "").splitlines() if x.strip()][:12]
        say(f"signed in: {signed} | page: {' / '.join(tail)[:300]}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or NAMES))
