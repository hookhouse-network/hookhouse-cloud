"""On every open 'Create a Page' tab: REPLACE the Bio with the channel's exact Facebook bio (native value setter, no
typing) and read it back. 19 Nov: fb_page_category pasted the bio a second time into the box (a simulated Ctrl+A
selects nothing in Chrome), so the forms showed it doubled. python -m scripts.fb_page_bio_fix"""
import asyncio
import json
import sys
import urllib.request

import websockets

from engine import brand_art
from engine.config import channels

SET = r'''((label, value) => {
  const e = [...document.querySelectorAll("input,textarea")].find(x => (x.closest("label") ? x.closest("label").innerText : "").startsWith(label));
  if (!e) return null;
  const proto = e.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(e, value);
  e.dispatchEvent(new Event("input", {bubbles: true}));
  e.dispatchEvent(new Event("change", {bubbles: true}));
  return e.value; })(%s, %s)'''
GET = r'''((label) => { const e = [...document.querySelectorAll("input,textarea")].find(x => (x.closest("label") ?
  x.closest("label").innerText : "").startsWith(label)); return e ? e.value : null; })(%s)'''


def expected(name: str) -> tuple[str, str] | None:
    for c in channels():
        if c["name"] == name.strip():
            return c["id"], brand_art.BIOS.get(c["id"], ("", (c.get("about") or "")[:100]))[1]
    return None


async def fix(tab) -> str:
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def js(e):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": "Runtime.evaluate", "params": {"expression": e,
                                                                                         "returnByValue": True}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return (r.get("result", {}).get("result") or {}).get("value")
        name = await js(GET % json.dumps("Page name")) or ""
        exp = expected(name)
        if not exp:
            return f"{name!r}: not one of our channels, left alone"
        cid, bio = exp
        if name != name.strip() or len(name) > 60:
            await js(SET % (json.dumps("Page name"), json.dumps(name.strip()[:60])))
        got = await js(SET % (json.dumps("Bio"), json.dumps(bio)))
        ok = got == bio and (await js(GET % json.dumps("Bio"))) == bio
        return f"{name}: bio {'exact' if ok else 'STILL WRONG'} ({len(bio)} chars)"


async def main():
    tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
            if t["type"] == "page" and "pages/creation" in t["url"]]
    for t in tabs:
        sys.stdout.buffer.write((await fix(t) + "\n").encode("utf-8"))

asyncio.run(main())
