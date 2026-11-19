"""Log in to our Instagram accounts with the owner's password from .env (IG_SIGNUP_PASSWORD, "use that in all", owner
19 Nov) in a temporary private window of the HookHouse Chrome; a security code, if asked, comes from the HookHouse
Gmail. The login is saved to data/secrets/ig_session_<user>.json (never printed or uploaded).
python -m scripts.ig_login <username> [...]"""
import asyncio
import json
import os
import re
import sys
import time

from engine.config import ROOT, load_env
from scripts.ig_context_login import Browser
from scripts.ig_signup_finish import gmail_code

KEEP = ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires")
FILL = r'''((names, v) => { const e = [...document.querySelectorAll("input")].find(i => names.some(n =>
  ((i.getAttribute("aria-label") || "") + " " + (i.name || "") + " " + ((i.closest("label") || {}).innerText || ""))
  .toLowerCase().includes(n))); if (!e) return false; e.focus();
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(e, v);
  e.dispatchEvent(new Event("input", {bubbles: true})); e.dispatchEvent(new Event("change", {bubbles: true}));
  return e.value === v; })(%s, %s)'''
BTN = r'''((labels) => { const b = [...document.querySelectorAll("button,div[role=button],input[type=submit]")].filter(e =>
  labels.includes((e.innerText || e.value || "").trim()) && e.getBoundingClientRect().width > 0 && !e.disabled).pop();
  if (!b) return null;
  b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })(%s)'''


async def login(b: Browser, user: str, pw: str) -> str:
    ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
    try:
        t = await b.cmd("Target.createTarget", {"url": "https://www.instagram.com/accounts/login/", "browserContextId": ctx})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            r = await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)
            return (r.get("result") or {}).get("value")

        async def press(labels):
            xy = await js(BTN % json.dumps(labels))
            if not xy:
                return False
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left",
                                                         "clickCount": 1}, s)
            return True
        for _ in range(20):
            time.sleep(1.5)
            if await js('document.querySelectorAll("input").length >= 2'):
                break
        async def type_into(selector, text):            # 19 Nov: script-set values are ignored here: real typing
            xy = await js('(() => { const e = document.querySelector(%s); if (!e) return null; e.scrollIntoView({block: '
                          '"center"}); const r = e.getBoundingClientRect(); return [r.x + 12, r.y + r.height / 2]; })()'
                          % json.dumps(selector))
            if not xy:
                return False
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left",
                                                         "clickCount": 1}, s)
            await b.cmd("Input.insertText", {"text": text}, s)
            return True
        if await type_into('input[name="email"], input[name="username"]', user) and \
                await type_into('input[name="pass"], input[name="password"], input[type="password"]', pw):
            ok_u = ok_p = True
        else:
            ok_u = await js(FILL % (json.dumps(["username", "phone number", "email"]), json.dumps(user)))
            ok_p = await js(FILL % (json.dumps(["password", "pass"]), json.dumps(pw)))
        if not (ok_u and ok_p):
            return f"@{user}: login form not found"
        since = time.time()
        await press(["Log in", "Log In"])
        page = ""
        for _ in range(15):
            time.sleep(2)
            page = await js("document.body.innerText") or ""
            if re.search(r"incorrect|wasn.t right|check your password", page, re.I):
                return f"@{user}: password not accepted (this account may use another password)"
            if re.search(r"security code|enter the code|confirmation code|we sent", page, re.I):
                code = await gmail_code("", since)
                if not code:
                    return f"@{user}: Instagram asked for a code and none arrived in Gmail"
                await js(FILL % (json.dumps(["code", "security"]), json.dumps(code)))
                await press(["Confirm", "Submit", "Continue", "Next"])
                time.sleep(8)
            if "/accounts/login" not in (await js("location.href") or ""):
                break
        await press(["Not now", "Not Now"])
        time.sleep(3)
        ck = [c for c in (await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", [])
              if c["domain"].endswith("instagram.com")]
        if not any(c["name"] == "sessionid" for c in ck):
            return f"@{user}: not logged in ({page[:80]!r})"
        ck = [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))} for c in ck]
        (ROOT / "data" / "secrets" / f"ig_session_{user}.json").write_text(json.dumps(ck), encoding="utf-8")
        return f"@{user}: logged in, login saved"
    finally:
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})


async def main(users):
    load_env()
    pw = os.environ.get("IG_SIGNUP_PASSWORD", "")
    if len(pw) < 6:
        print("IG_SIGNUP_PASSWORD is empty in .env")
        return
    async with Browser() as b:
        for u in users:
            print(await login(b, u, pw), flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
