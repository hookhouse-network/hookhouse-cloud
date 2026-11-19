"""Sign the headless HookHouse Chrome in to the HookHouse Kick account (data/secrets/kick_account.json; password
IG_SIGNUP_PASSWORD from .env, never printed). Handles a sign-up / login code from the HookHouse Gmail.
python -m scripts.kick_login"""
import asyncio
import json
import os
import re
import sys
import time

from engine.config import load_env
from engine.kick import _Tab
from scripts.kick_signup import ACCOUNT, fill, gmail_code, say


async def main() -> None:
    load_env()
    acc = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    async with _Tab("https://kick.com/") as tab:
        await asyncio.sleep(12)
        await tab.click_text("Confirm My Choices")
        if not await tab.click_text("Log In"):
            say("no Log In button")
            return
        await asyncio.sleep(5)
        sel_user = "input[name=emailOrUsername], input[name=username], input[name=email]"
        ok = await tab.js(f"!!document.querySelector({json.dumps(sel_user)})")
        if not ok:
            say("login form not found: " + (await tab.js("document.body.innerText") or "")[:300].replace("\n", " / "))
            return
        name = await tab.js(f"document.querySelector({json.dumps(sel_user)}).name")
        await fill(tab, f"input[name={name}]", acc["username"])
        await fill(tab, "input[name=password]", os.environ.get("IG_SIGNUP_PASSWORD", ""))
        since = time.time()
        xy = await tab.js("""(() => { const f = document.querySelector('input[name=password]').closest('form');
          const b = [...f.querySelectorAll('button[type=submit]')].find(x => (x.innerText || '').trim() === 'Log In');
          if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
        for k in ("mouseMoved", "mousePressed", "mouseReleased"):
            await tab.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
        await asyncio.sleep(8)
        if await tab.js("!!document.querySelector('input[autocomplete=one-time-code], input[name*=code], input[inputmode=numeric]')"):
            code = await gmail_code(since)
            say(f"code needed; found: {bool(code)}")
            if code:
                await tab.js("document.querySelector('input[autocomplete=one-time-code], input[name*=code], input[inputmode=numeric]').focus()")
                await tab.cmd("Input.insertText", {"text": code})
                await asyncio.sleep(3)
                await tab.click_text("Verify", "Confirm", "Submit", "Continue", "Log In")
                await asyncio.sleep(8)
        txt = await tab.js("document.body.innerText") or ""
        errs = [x for x in txt.splitlines() if re.search(r"invalid|incorrect|wrong|not found|too many|verify", x, re.I)]
        signed = "Log In" not in txt.split("\n", 30)[0:30]
        signed = not await tab.js("[...document.querySelectorAll('button')].some(b => (b.innerText || '').trim() === 'Log In' && b.getBoundingClientRect().width > 0)")
        acc["signed_in"] = bool(signed)
        ACCOUNT.write_text(json.dumps(acc), encoding="utf-8")
        say(f"signed in: {signed}" + (f" | page says: {' / '.join(errs)[:200]}" if errs else ""))


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
