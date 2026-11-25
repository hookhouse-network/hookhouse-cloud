"""Pinterest business profile of a channel (hidden, from its saved login): name, username = the channel's handle if
free, about with follow lines (YouTube, Instagram, Threads), website = the YouTube channel, profile picture.
python -m scripts.pinterest_profile <channel_id>"""
import asyncio
import json
import re
import sys
import time

from engine import brand_art
from engine.config import ROOT, channel
from engine.links import _ig_connected, data as links
from scripts.ig_context_login import Browser


def about_for(cid: str) -> str:
    row = links().get(cid) or {}
    first = "\n".join(brand_art.BIOS.get(cid, ("",))[0].split("\n")[:2])
    follow = []
    if row.get("youtube"):
        follow.append(f"▶️ YouTube {row['youtube']}")
    ig = str(row.get("instagram") or "").lstrip("@")
    if ig and _ig_connected(cid):
        follow.append(f"📸 Instagram @{ig}")
        if row.get("threads_live"):
            follow.append(f"🧵 Threads @{ig}")
    return (first + ("\nFollow us: " + " · ".join(follow) if follow else ""))[:500]


async def main(cid: str):
    ch, row = channel(cid), links().get(cid) or {}
    want_user = str(row.get("youtube") or "").lstrip("@").lower()[:30]
    website = f"https://www.youtube.com/{row['youtube']}" if row.get("youtube") else ""
    async with Browser() as b:
        ctx = (await b.cmd("Target.createBrowserContext"))["browserContextId"]
        await b.cmd("Storage.setCookies", {"cookies": json.loads((ROOT / "data" / "secrets" / f"pinterest_session_{cid}.json")
                                                                   .read_text(encoding="utf-8")), "browserContextId": ctx})
        t = await b.cmd("Target.createTarget", {"url": "https://www.pinterest.com/settings/edit-profile/", "browserContextId": ctx})
        s = (await b.cmd("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}))["sessionId"]

        async def js(e):
            return ((await b.cmd("Runtime.evaluate", {"expression": e, "returnByValue": True}, s)).get("result") or {}).get("value")

        async def click(xy):
            for k in ("mouseMoved", "mousePressed", "mouseReleased"):
                await b.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1}, s)

        async def replace(sel, text):
            xy = await js('(() => { const e = document.querySelector(%s); if (!e) return null; e.scrollIntoView({block: "center"});'
                          ' const r = e.getBoundingClientRect(); return [r.x + 12, r.y + Math.min(r.height / 2, 14)]; })()'
                          % json.dumps(sel))
            if not xy:
                return False
            await click(xy)
            await b.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2,
                                                   "commands": ["selectAll"]}, s)
            await b.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2}, s)
            await b.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Backspace", "code": "Backspace",
                                                   "windowsVirtualKeyCode": 8}, s)
            await b.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Backspace", "code": "Backspace",
                                                   "windowsVirtualKeyCode": 8}, s)
            await b.cmd("Input.insertText", {"text": text}, s)
            time.sleep(0.6)
            return (await js('document.querySelector(%s).value' % json.dumps(sel))) == text
        for _ in range(15):
            time.sleep(1.5)
            if await js('!!document.querySelector("input[name=business_name]")'):
                break
        async def save_now():                           # 25 Nov: one save for all fields did not stick on new
            sxy = await js('(() => { const b = [...document.querySelectorAll("button")].filter(e => (e.innerText || "")'   # accounts;
                           '.trim() === "Save" && e.getBoundingClientRect().width > 0 && !e.disabled).pop(); if (!b) return null;'
                           ' b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();'  # each field alone did
                           ' return [r.x + r.width / 2, r.y + r.height / 2]; })()')
            if sxy:
                await click(sxy)
                time.sleep(4)
        res = {"name": await replace("input[name=business_name]", ch["name"])}
        await save_now()
        res["about"] = await replace("textarea[name=about], textarea#about", about_for(cid))
        await save_now()
        if website:
            res["website"] = await replace("input[name=website_url], input#website_url", website)
            await save_now()
        if want_user:
            await replace("input[name=username], input#username", want_user)
            time.sleep(3)
            field = await js('(() => { const e = document.querySelector("input[name=username]"); const box = e && '
                             '(e.closest("div[class]") || e.parentElement); return box ? box.parentElement.innerText : ""; })()')
            taken = bool(re.search(r"taken|not available|already", field or "", re.I))   # near the field only
            res["username"] = "taken (kept the old one)" if taken else want_user
            if taken:
                await replace("input[name=username], input#username", (want_user + "pins")[:30])
                res["username"] = (want_user + "pins")[:30]
            await save_now()
        avatar = ROOT / "output" / "brand" / cid / "avatar.png"
        xy = await js('(() => { const b = [...document.querySelectorAll("button,div[role=button]")].find(e => (e.innerText || "")'
                      '.trim() === "Change" && e.getBoundingClientRect().width > 0); if (!b) return null; b.scrollIntoView({block:'
                      ' "center"}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()')
        if xy:                                           # the photo upload box only exists after "Change"
            await click(xy)
            time.sleep(2.5)
        await b.cmd("DOM.enable", {}, s)
        doc = await b.cmd("DOM.getDocument", {"depth": -1, "pierce": True}, s)
        q = await b.cmd("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"}, s)
        if avatar.exists() and q.get("nodeIds"):
            await b.cmd("DOM.setFileInputFiles", {"nodeId": q["nodeIds"][0], "files": [str(avatar.resolve())]}, s)
            time.sleep(6)
            for lbl in ("Done", "Save"):
                xy = await js('((w) => { const b = [...document.querySelectorAll("[role=dialog] button")].find(e => (e.innerText || "")'
                              '.trim() === w); if (!b) return null; const r = b.getBoundingClientRect(); return [r.x + r.width / 2,'
                              ' r.y + r.height / 2]; })(%s)' % json.dumps(lbl))
                if xy:
                    await click(xy)
                    time.sleep(3)
                    break
            res["photo"] = "uploaded"
        xy = await js('(() => { const b = [...document.querySelectorAll("button")].filter(e => (e.innerText || "").trim() === "Save"'
                      ' && e.getBoundingClientRect().width > 0 && !e.disabled).pop(); if (!b) return null; b.scrollIntoView({block:'
                      ' "center"}); const r = b.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()')
        if xy:
            await click(xy)
            time.sleep(6)
        await b.cmd("Page.reload", {}, s)
        for _ in range(20):                              # the form renders late; reading too early gave None
            time.sleep(2)
            if await js('!!document.querySelector("input[name=business_name]")'):
                break
        saved = await js('[document.querySelector("input[name=business_name]").value, document.querySelector("input[name=username]").value,'
                         ' (document.querySelector("input[name=website_url]") || {}).value]')
        print(f"{cid}: {res} -> saved: name={saved[0]!r} user={saved[1]!r} website={saved[2]!r}")
        await b.cmd("Target.disposeBrowserContext", {"browserContextId": ctx})
        if saved and saved[0] == ch["name"]:
            from engine.links import set_link
            set_link(cid, pinterest=saved[1])

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
