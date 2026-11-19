"""Set the linked Instagram bio (brand_art.ig_bio: two lines + "Follow on YouTube: @handle") on every account whose
login is saved in data/secrets/ig_session_<user>.json. Each account opens in its own temporary private window of the
HookHouse Chrome (works hidden), the bio is read back, the window is closed. python -m scripts.ig_bio_all [cid ...]"""
import asyncio
import json
import sys
import time

from engine import brand_art
from engine.config import ROOT
from engine.links import data as links
from scripts.ig_bio import SET, SUBMIT
from scripts.ig_context_login import Browser

SECRETS = ROOT / "data" / "secrets"


async def one(b: Browser, cid: str, user: str) -> str:
    f = SECRETS / f"ig_session_{user}.json"
    if not f.exists():
        return f"{cid}: no saved login for @{user}"
    ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
    try:
        await b.cmd("Storage.setCookies", {"cookies": json.loads(f.read_text(encoding="utf-8")), "browserContextId": ctx})
        t = await b.cmd("Target.createTarget", {"url": "https://www.instagram.com/accounts/edit/", "browserContextId": ctx})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            r = await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)
            return (r.get("result") or {}).get("value")
        for _ in range(20):
            time.sleep(1.5)
            if await js('!!document.querySelector("textarea")'):
                break
        else:
            return f"{cid}: edit page did not open (login expired?)"
        bio = brand_art.ig_bio(cid)
        if (await js('document.querySelector("textarea").value')) == bio:
            return f"{cid}: @{user} bio already linked"
        await js(SET % json.dumps(bio))
        time.sleep(1)
        await js(SUBMIT)
        time.sleep(5)
        await b.cmd("Page.reload", {}, s)
        for _ in range(15):
            time.sleep(1.5)
            if await js('!!document.querySelector("textarea")'):
                break
        ok = (await js('document.querySelector("textarea").value')) == bio
        return f"{cid}: @{user} bio {'linked (read back)' if ok else 'NOT saved'}"
    finally:
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})


async def main(only):
    async with Browser() as b:
        for cid, row in links().items():
            if not isinstance(row, dict) or (only and cid not in only) or cid not in brand_art.BIOS:
                continue
            user = str(row.get("instagram") or "").lstrip("@")
            if user and (SECRETS / f"ig_session_{user}.json").exists():
                print(await one(b, cid, user), flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
