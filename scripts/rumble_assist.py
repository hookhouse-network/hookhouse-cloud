"""Rumble sign-up with one human click: opens a visible HookHouse window with email + birthday filled; the owner presses
Next (Rumble's invisible robot check wants a real click); then this script fills the next steps (username, password
from .env, the Gmail code), presses on, and saves the login to data/secrets/rumble_session.json.
python -m scripts.rumble_assist [username]"""
import asyncio
import json
import os
import re
import sys
import time

from engine.config import ROOT, load_env
from scripts.ig_context_login import Browser
from scripts.rumble_signup import EMAIL, KEEP, rumble_code


async def main(username: str):
    load_env()
    pw = os.environ.get("IG_SIGNUP_PASSWORD", "")
    y, mo, d = os.environ["IG_SIGNUP_BIRTHDATE"].strip().split("-")
    async with Browser() as b:
        ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
        t = await b.cmd("Target.createTarget", {"url": "https://rumble.com/register/", "browserContextId": ctx, "newWindow": True})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            try:
                return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")
            except Exception:  # noqa: BLE001 - page navigating
                return None

        async def type_into(sel, text):
            if not await js('(() => { const e = document.querySelector(%s); if (!e || e.value) return false; e.focus(); return true; })()'
                            % json.dumps(sel)):
                return False
            await b.cmd("Input.insertText", {"text": text}, s)
            return True
        await b.cmd("Target.activateTarget", {"targetId": t["targetId"]})
        for _ in range(20):
            if "auth.rumble.com" in (await js("location.host") or "") and await js('!!document.querySelector("input[name=email]")'):
                break
            time.sleep(1.5)
        time.sleep(3)
        await type_into("input[name=email]", EMAIL)
        for name, val in (("birthday_month", str(int(mo) - 1)), ("birthday_day", str(int(d))), ("birthday_year", y)):
            await js('((n, v) => { const s = document.querySelector("select[name=" + n + "]"); Object.getOwnPropertyDescriptor('
                     'HTMLSelectElement.prototype, "value").set.call(s, v); s.dispatchEvent(new Event("change", {bubbles: true}));'
                     ' })(%s, %s)' % (json.dumps(name), json.dumps(val)))
        print("filled: press Next in the Rumble window", flush=True)
        since, done, seen = time.time(), False, set()
        for _ in range(240):                                       # up to 20 minutes
            time.sleep(5)
            page = await js("document.body.innerText") or ""
            host = await js("location.host") or ""
            if "rumble.com" in host and "auth." not in host and "/register" not in (await js("location.pathname") or ""):
                done = True
                break
            if await type_into("input[name=username], #username", username):
                seen.add("username")
            for sel in ("input[name=password]", "input[name=password_confirm], input[name=confirm_password], input[name=passwordConfirm]"):
                if await type_into(sel, pw):
                    seen.add("password")
            if re.search(r"(enter|confirmation|verification) code|check your email|sent .* code", page, re.I) and "code" not in seen:
                code = await rumble_code(b, since)
                if code and await type_into("input[name=code], input[name*=code], input[autocomplete=one-time-code], "
                                            "input[inputmode=numeric]", code):
                    seen.add("code")
                    print("code entered", flush=True)
        ck = [c for c in (await b.cmd("Storage.getCookies", {"browserContextId": ctx})).get("cookies", []) if "rumble" in c["domain"]]
        ck = [{k: c[k] for k in KEEP if k in c and not (k == "expires" and c[k] in (-1, None))} for c in ck]
        (ROOT / "data" / "secrets" / "rumble_session.json").write_text(json.dumps(ck), encoding="utf-8")
        print(f"{'account ready' if done else 'stopped'} (filled: {', '.join(sorted(seen)) or 'first step only'}; "
              f"at {(await js('location.href') or '')[:70]})", flush=True)
        time.sleep(3)
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "HookHouseMedia"))
