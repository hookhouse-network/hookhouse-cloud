"""Rumble account "HookHouse Media" (owner 19 Nov: "yes add rumble"), hidden: email alias of the HookHouse Gmail,
birth date + password from .env, username, confirmation code from Gmail; the login is saved to
data/secrets/rumble_session.json. Stops (and says so) at a robot check. python -m scripts.rumble_signup [username]"""
import asyncio
import json
import os
import re
import sys
import time
import urllib.parse

from engine.config import ROOT, load_env
from scripts.ig_context_login import Browser

KEEP = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")
EMAIL = "hook.house.network@gmail.com"   # 19 Nov: Rumble resets on "+" addresses; Gmail ignores dots
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]


async def rumble_code(b: Browser, since: float, wait_s: int = 240) -> str | None:
    """Newest Rumble code in the HookHouse Gmail (main profile tab)."""
    import urllib.request
    import websockets
    tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read()) if t["type"] == "page"]
    t = next((t for t in tabs if "mail.google.com" in t["url"]), None)
    if t is None:
        req = urllib.request.Request("http://127.0.0.1:9333/json/new?https://mail.google.com/mail/u/0/", method="PUT")
        t = json.loads(urllib.request.urlopen(req).read())
        time.sleep(10)
    q = urllib.parse.quote("from:rumble newer_than:20m")
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def ev(e):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": "Runtime.evaluate", "params": {"expression": e, "returnByValue": True}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return (r.get("result", {}).get("result") or {}).get("value")
        while time.time() - since < wait_s:
            await ev(f'location.href = "https://mail.google.com/mail/u/0/#search/{q}"')
            time.sleep(8)
            txt = await ev('(document.querySelector("[role=main]") || document.body).innerText') or ""
            m = re.search(r"\b(\d{4,8})\b(?=[^\n]{0,80}(code|verif))|(code|verif)[^\n]{0,60}?\b(\d{4,8})\b", txt, re.I)
            if m:
                return m.group(1) or m.group(4)
            time.sleep(7)
    return None


async def main(username: str):
    load_env()
    pw, born = os.environ.get("IG_SIGNUP_PASSWORD", ""), os.environ.get("IG_SIGNUP_BIRTHDATE", "").strip()
    y, mo, d = born.split("-")
    async with Browser() as b:
        ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
        t = await b.cmd("Target.createTarget", {"url": "https://rumble.com/register/", "browserContextId": ctx,
                                                "newWindow": True})      # visible window: its robot check passes there
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")

        async def click(xy):
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1}, s)

        async def fill(sel, text):
            xy = await js('(() => { const e = document.querySelector(%s); if (!e || e.value) return null; e.scrollIntoView('
                          '{block: "center"}); const r = e.getBoundingClientRect(); return [r.x + 12, r.y + r.height / 2]; })()'
                          % json.dumps(sel))
            if not xy:
                return False
            await click(xy)
            await b.cmd("Input.insertText", {"text": text}, s)
            return True

        async def select(which, value):
            return await js('((w, v) => { const s = [...document.querySelectorAll("select")].find(x => ((x.name || "") + (x.id || "") +'
                            ' (x.getAttribute("aria-label") || "")).toLowerCase().includes(w)); if (!s) return null; const o = [...s.options]'
                            '.find(o => o.value === v || o.text.trim() === v); if (!o) return false; Object.getOwnPropertyDescriptor('
                            'HTMLSelectElement.prototype, "value").set.call(s, o.value); s.dispatchEvent(new Event("change", {bubbles:'
                            ' true})); return true; })(%s, %s)' % (json.dumps(which), json.dumps(value)))

        async def press():
            xy = await js('(() => { const b = [...document.querySelectorAll("button,input[type=submit]")].filter(e => /^(continue|'
                          'next|sign up|create account|register|verify|submit|done)$/i.test((e.innerText || e.value || "").trim()) &&'
                          ' e.getBoundingClientRect().width > 0 && !e.disabled).pop(); if (!b) return null; b.scrollIntoView({block:'
                          ' "center"}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2,'
                          ' (b.innerText || b.value || "").trim()]; })()')
            if not xy:
                return None
            await click(xy)
            return xy[2]
        await b.cmd("Target.activateTarget", {"targetId": t["targetId"]})
        steps, since = [], time.time()
        time.sleep(10)
        for _ in range(12):
            page = await js("document.body.innerText") or ""
            if re.search(r"captcha|not a robot|verify you are human", page, re.I) and not re.search(r"code", page, re.I):
                print("Rumble shows a robot check: owner needed")
                break
            if await fill("input[name=email], input[type=email], #email", EMAIL):
                steps.append("email")
            for w, v in (("month", MONTHS[int(mo) - 1]), ("day", d), ("year", y)):   # month values start at 0: by name
                await select(w, v)
            if await fill("input[name=username], #username", username):
                steps.append("username")
            for sel in ("input[name=password], #password", "input[name=password_confirm], input[name=confirm_password],"
                                                          " input[name=passwordConfirm], #password_confirm"):
                if await fill(sel, pw):
                    steps.append("password")
            await js('[...document.querySelectorAll("input[type=checkbox]")].filter(c => !c.checked && /terms|agree|age|policy/i'
                     '.test(((c.closest("label") || c.parentElement || {}).innerText || ""))).forEach(c => c.click())')
            if re.search(r"(enter|confirmation|verification) code|check your email", page, re.I):
                code = await rumble_code(b, since)
                if not code:
                    print("no Rumble code in Gmail")
                    break
                await fill("input[name=code], input[name*=code], input[autocomplete=one-time-code], input[inputmode=numeric]", code)
                steps.append("code")
            got = await press()
            if not got:
                break
            steps.append(got)
            time.sleep(7)
            if "rumble.com" in (await js("location.host") or "") and "/register" not in (await js("location.pathname") or "") \
                    and "auth." not in (await js("location.host") or ""):
                break
        ck = [c for c in (await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", [])
              if "rumble" in c["domain"]]
        ck = [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))} for c in ck]
        (ROOT / "data" / "secrets" / "rumble_session.json").write_text(json.dumps(ck), encoding="utf-8")
        print(f"steps: {', '.join(steps)} | at {(await js('location.href') or '')[:80]}")
        print((await js("document.body.innerText.slice(0,240)") or "").replace("\n", " / "))
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "HookHouseMedia"))
