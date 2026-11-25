"""Pinterest business account for a channel, hidden (owner 19 Nov: complete Pinterest; password + birth date from .env):
email hookhouse.network+<channel>@gmail.com -> Create account -> business name + steps (Next / Skip) -> login saved to
data/secrets/pinterest_session_<cid>.json -> handle recorded in config/links.yaml (pinterest:).
python -m scripts.pinterest_new <channel_id>"""
import asyncio
import json
import os
import re
import sys
import time

from engine.config import ROOT, channel, load_env
from scripts.ig_context_login import Browser

KEEP = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")
NEXT = ["Next", "Skip", "Continue", "Done", "Not now", "Get started", "Skip for now", "Save", "Finish"]


async def main(cid: str):
    load_env()
    pw, born = os.environ.get("IG_SIGNUP_PASSWORD", ""), os.environ.get("IG_SIGNUP_BIRTHDATE", "").strip()
    if len(pw) < 8 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", born):
        print("IG_SIGNUP_PASSWORD (8+ characters) and IG_SIGNUP_BIRTHDATE are needed in .env")
        return
    ch = channel(cid)
    email = f"hookhouse.network+{cid.replace('_', '')}@gmail.com"
    async with Browser() as b:
        ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
        t = await b.cmd("Target.createTarget", {"url": "https://www.pinterest.com/business/create/", "browserContextId": ctx})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")

        async def click(xy):
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1}, s)

        async def type_into(sel, text):
            xy = await js('(() => { const e = document.querySelector(%s); if (!e) return null; e.scrollIntoView({block: "center"});'
                          ' const r = e.getBoundingClientRect(); return [r.x + 12, r.y + r.height / 2]; })()' % json.dumps(sel))
            if not xy:
                return False
            await click(xy)
            await b.cmd("Input.insertText", {"text": text}, s)
            return True

        async def press(labels):
            q = ('((labels) => { const b = [...document.querySelectorAll("button,div[role=button],a[role=button]")].filter(e => '
                 'labels.includes((e.innerText || e.getAttribute("aria-label") || "").trim()) && e.getBoundingClientRect().width > 0'
                 ' && !e.disabled && e.getAttribute("aria-disabled") !== "true").pop(); if (!b) return null; b.scrollIntoView('
                 '{block: "center"}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2, '
                 '(b.innerText || b.getAttribute("aria-label") || "").trim()]; })(%s)' % json.dumps(labels))
            xy = await js(q)
            if not xy:
                return None
            time.sleep(0.4)
            xy = await js(q)
            await click(xy)
            return xy[2]
        time.sleep(10)
        ok = (await type_into("input[name=email], #email", email) and await type_into("input[name=password], #password", pw))
        await js('((v) => { const e = document.querySelector("input[type=date], #birthdate"); if (!e) return false;'
                 ' Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(e, v);'
                 ' e.dispatchEvent(new Event("input", {bubbles: true})); e.dispatchEvent(new Event("change", {bubbles: true}));'
                 ' return e.value === v; })(%s)' % json.dumps(born))
        if not ok:
            print(f"{cid}: sign-up form not found")
            return
        await press(["Create account"])
        time.sleep(10)
        steps = []
        for _ in range(14):
            page = await js("document.body.innerText") or ""
            if re.search(r"already (an )?account|already in use|already registered", page, re.I):
                print(f"{cid}: Pinterest says this email already has an account")
                break
            name_box = await js('!!document.querySelector("input[name=business_name], input[id*=business], input[placeholder*=usiness]")')
            if name_box and not await js('(document.querySelector("input[name=business_name], input[id*=business], '
                                         'input[placeholder*=usiness]") || {}).value'):
                await type_into("input[name=business_name], input[id*=business], input[placeholder*=usiness]", ch["name"])
                steps.append("name")
            got = await press(NEXT)
            if not got:
                break
            steps.append(got)
            time.sleep(6)
        ck = [c for c in (await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", [])
              if "pinterest" in c["domain"]]
        logged = any(c["name"] in ("_pinterest_sess", "_auth") for c in ck)
        user = await js('(() => { const a = [...document.querySelectorAll("a[href]")].map(x => x.getAttribute("href"))'
                        '.find(h => /^\\/[A-Za-z0-9_]+\\/$/.test(h) && !/^\\/(business|ideas|today|settings|search)\\/$/.test(h));'
                        ' return a ? a.replaceAll("/", "") : ""; })()') or ""
        if logged:
            ck = [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))} for c in ck]
            (ROOT / "data" / "secrets" / f"pinterest_session_{cid}.json").write_text(json.dumps(ck), encoding="utf-8")
        if not steps or not user:                       # 25 Nov: say what the page shows when nothing went through
            print(f"{cid}: page says: " + ((await js("document.body.innerText")) or "")[:300].replace("\n", " / "))
        print(f"{cid}: {'account created' if logged else 'not confirmed'} (steps: {', '.join(steps) or 'none'}; "
              f"user {user or '?'}; at {(await js('location.pathname')) or ''})")
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
