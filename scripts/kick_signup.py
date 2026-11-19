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


async def gmail_code(since: float, wait_s: int = 240, exclude: set | None = None) -> str | None:
    """Newest Kick code mail of the last 15 minutes (sign-ups run one at a time)."""
    q = urllib.parse.quote("from:kick newer_than:15m")
    async with _Tab(f"https://mail.google.com/mail/u/0/#search/{q}") as gm:
        while time.time() - since < wait_s:
            await asyncio.sleep(10)
            body = await gm.js('(document.querySelector("[role=main]") || document.body).innerText') or ""
            codes = re.findall(r"(\d{6}) - Sign Up Verification Code", body)
            fresh = [c for c in codes if c not in (exclude or set())]
            if fresh:
                return fresh[0]                              # newest first; never an older attempt's code
            await gm.js("location.reload()")
    return None


async def existing_codes() -> set:
    q = urllib.parse.quote("from:kick newer_than:1d")
    async with _Tab(f"https://mail.google.com/mail/u/0/#search/{q}") as gm:
        await asyncio.sleep(10)
        body = await gm.js('(document.querySelector("[role=main]") || document.body).innerText') or ""
    return set(re.findall(r"(\d{6}) - Sign Up Verification Code", body))


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
        old_codes = await existing_codes()
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
        for _ in range(6):
            await asyncio.sleep(2)
            dl = await tab.js("[...document.querySelectorAll('[role=dialog]')].map(d => d.innerText.trim()).filter(t => t && !t.startsWith('Your Privacy')).join(' || ')") or ""
            say("after Sign Up: " + " / ".join(dl[:300].splitlines()))
        txt = await tab.js("document.body.innerText") or ""
        if re.search(r"captcha|robot|verify you are human|challenge", txt, re.I):
            say("ROBOT CHECK shown: the owner must tick it (visible window)")
            return
        DLG = ("[...document.querySelectorAll('[role=dialog]')].find(d => (d.innerText || '').includes('Email Verification'))")
        code_box = await tab.js(f"(() => {{ const d = {DLG}; return d ? d.querySelectorAll('input').length : 0; }})()")
        say(f"signed up as {user}; code fields in the verification dialog: {code_box}")
        if code_box:
            code = await gmail_code(since, exclude=old_codes)
            if not code:
                say("no Kick code mail within 4 minutes")
                return
            xy = await tab.js(f"(() => {{ const d = {DLG}; if (!d) return null; const e = d.querySelector('input');"
                              " const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
            if not xy:
                say("the verification dialog closed before the code arrived")
                return
            info = await tab.js(f"(() => {{ const d = {DLG}; const e = d.querySelector('input'); return [e.type, e.name, e.maxLength, e.inputMode, e.autocomplete, e.outerHTML.slice(0, 200)]; }})()")
            say(f"code field: {info}")
            await tab.js(f"(() => {{ const d = {DLG}; d.querySelector('input').focus(); }})()")
            alive = await tab.js(f"!!({DLG})")
            say(f"after focus, dialog open: {alive}")
            await tab.cmd("Network.enable")
            await tab.cmd("Input.insertText", {"text": code})
            t_end = time.time() + 8
            while time.time() < t_end:                       # what Kick's server answered (status only, no bodies)
                try:
                    r = json.loads(await asyncio.wait_for(tab.ws.recv(), timeout=1))
                except asyncio.TimeoutError:
                    continue
                if r.get("method") == "Network.responseReceived":
                    u = r["params"]["response"]["url"]
                    if "kick.com" in u and ("/api/" in u or "/register" in u or "/signup" in u or "verif" in u):
                        say(f"  server: {r['params']['response']['status']} {u.split('?')[0][-70:]}")
                    if r["params"]["response"]["status"] >= 400 and "kick.com" in u:
                        rid = r["params"]["requestId"]
                        await tab.ws.send(json.dumps({"id": 99999, "method": "Network.getResponseBody", "params": {"requestId": rid}}))
            await asyncio.sleep(1)
            alive = await tab.js(f"(() => {{ const d = {DLG}; return d ? 'open: ' + d.querySelector('input').value.length + ' digits; ' + d.innerText.slice(0, 160) : 'closed'; }})()")
            say(f"after typing: {alive}")
            await asyncio.sleep(4)
            dl = await tab.js("[...document.querySelectorAll('[role=dialog],[role=alertdialog]')].map(d => d.innerText.trim())"
                              ".filter(t => t && !t.startsWith('Your Privacy')).join(' || ')") or ""
            say("after code: " + " / ".join(dl[:600].splitlines()))
            btns = await tab.js("[...document.querySelectorAll('[role=dialog] button,[role=alertdialog] button')].filter(b => b.getBoundingClientRect().width > 0).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim())")
            say(f"buttons: {btns}")
            if "I accept" in (btns or []):                   # owner 20 Nov: "do all the steps by yourself"
                box = await tab.js("""(() => { const d = [...document.querySelectorAll('[role=dialog]')].find(x => x.innerText.includes('Please accept the terms'));
                  const sc = [...d.querySelectorAll('*')].find(e => e.scrollHeight > e.clientHeight + 50 && getComputedStyle(e).overflowY !== 'visible');
                  const r = (sc || d).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
                for _ in range(120):                         # read to the end with the mouse wheel
                    await tab.cmd("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": box[0], "y": box[1],
                                                               "deltaX": 0, "deltaY": 1500})
                    await asyncio.sleep(0.05)
                await asyncio.sleep(2)
                st = await tab.js("(() => { const b = [...document.querySelectorAll('[role=dialog] button')].find(x => (x.innerText || '').trim() === 'I accept'); return b ? {disabled: b.disabled, aria: b.getAttribute('aria-disabled')} : null; })()")
                say(f"I accept button: {st}")
                await tab.click_text("I accept")
                await asyncio.sleep(10)
                dl = await tab.js("[...document.querySelectorAll('[role=dialog],[role=alertdialog]')].map(d => d.innerText.trim())"
                                  ".filter(t => t && !t.startsWith('Your Privacy')).join(' || ')") or ""
                say("after accepting: " + " / ".join(dl[:300].splitlines()))
        signed = await tab.js("![...document.querySelectorAll('button')].some(b => (b.innerText || '').trim() === 'Log In' && b.getBoundingClientRect().width > 0)")
        ACCOUNT.parent.mkdir(parents=True, exist_ok=True)
        ACCOUNT.write_text(json.dumps({"username": user, "email": ALIAS, "created": time.strftime("%Y-%m-%d %H:%M"),
                                       "signed_in": bool(signed)}), encoding="utf-8")
        tail = [x for x in (await tab.js("document.body.innerText") or "").splitlines() if x.strip()][:12]
        say(f"signed in: {signed} | page: {' / '.join(tail)[:300]}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or NAMES))
