"""YouTube Studio (visible HookHouse Chrome): add the channel's own Instagram / Facebook links to its profile (shown
on the channel header and About), opening Studio straight from the channel id. Links already there are kept.
Owner 19 Nov: "link the same accounts on different platforms, specially Meta and YouTube".
python -m scripts.yt_links <channel_id> [<channel_id> ...]"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

from engine.config import ROOT, channel

IDS = json.loads((ROOT / "data" / "state" / "branding.json").read_text(encoding="utf-8"))
DEEP = r'''const all = []; const w = r => r.querySelectorAll("*").forEach(e => { all.push(e); if (e.shadowRoot) w(e.shadowRoot); });
w(document);'''
FIND_BTN = r'''(() => { %s const rx = new RegExp("^\\s*" + %%s + "\\s*$", "i");
  const b = all.filter(e => /^(BUTTON|YTCP-BUTTON|TP-YT-PAPER-BUTTON)$/.test(e.tagName) && e.offsetParent !== null
    && rx.test((e.innerText || e.getAttribute("aria-label") || "").trim())).pop();
  if (!b) return null; b.scrollIntoView({block: "center"}); const r = b.getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2]; })()''' % DEEP
INPUTS = r'''(() => { %s return all.filter(e => e.tagName === "INPUT" && e.offsetParent !== null).map(e => [e.getAttribute("aria-label")
  || e.placeholder || "", e.value]); })()''' % DEEP
FOCUS_EMPTY = r'''((n) => { %s const ins = all.filter(e => e.tagName === "INPUT" && e.offsetParent !== null && !e.value
  && !/search|email|channel name|handle/i.test(e.getAttribute("aria-label") || e.placeholder || ""));
  const e = ins[n]; if (!e) return null; e.scrollIntoView({block: "center"}); const r = e.getBoundingClientRect();
  return [r.x + 10, r.y + r.height / 2]; })(%%s)''' % DEEP


def wanted(cid: str) -> list[tuple[str, str]]:
    links = __import__("yaml").safe_load((ROOT / "config" / "links.yaml").read_text(encoding="utf-8")).get(cid) or {}
    out = []
    if links.get("instagram"):
        out.append(("Instagram", f"https://www.instagram.com/{str(links['instagram']).lstrip('@')}"))
    sec = ROOT / "data" / "secrets" / f"meta_{cid}.json"
    if links.get("facebook"):
        out.append(("Facebook", str(links["facebook"])))
    elif sec.exists():
        page = json.loads(sec.read_text(encoding="utf-8")).get("page_id")
        if page:
            out.append(("Facebook", f"https://www.facebook.com/{page}"))
    return out


async def run(cid: str) -> str:
    yt = IDS[cid]["youtube_id"]
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and "youtube.com" in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        n = 0

        async def cmd(m, p=None):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": m, "params": p or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return r.get("result", {})

        async def js(e):
            return (await cmd("Runtime.evaluate", {"expression": e, "returnByValue": True})).get("result", {}).get("value")

        async def click(xy):
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                await cmd("Input.dispatchMouseEvent", {"type": t, "x": xy[0], "y": xy[1], "button": "left",
                                                       "clickCount": 1})
        await cmd("Page.bringToFront")
        await cmd("Page.navigate", {"url": f"https://studio.youtube.com/channel/{yt}/editing/profile"})
        for _ in range(20):
            time.sleep(1.5)
            if await js(FIND_BTN % json.dumps("Add link")):
                break
        if yt not in (await js("location.href") or ""):
            return f"{cid}: Studio did not open this channel (other brand account)"
        have = " ".join(v for _, v in (await js(INPUTS) or []))
        todo = [(t, u) for t, u in wanted(cid) if u.rstrip("/").lower() not in have.lower()]
        if not todo:
            return f"{cid}: links already there"
        for title, url in todo:
            xy = await js(FIND_BTN % json.dumps("Add link"))
            if not xy:
                return f"{cid}: 'Add link' not found"
            time.sleep(0.8)
            xy = await js(FIND_BTN % json.dumps("Add link"))      # coordinates after scrolling
            await click(xy)
            time.sleep(1.5)
            for i, text in enumerate((title, url)):
                fxy = await js(FOCUS_EMPTY % "0")                    # the new row's empty title, then URL box
                if not fxy:
                    return f"{cid}: new link boxes not found"
                await click(fxy)
                time.sleep(0.3)
                await cmd("Input.insertText", {"text": text})
                time.sleep(0.5)
        time.sleep(1)
        pub = await js(FIND_BTN % json.dumps("Publish"))
        if not pub:
            return f"{cid}: Publish not found"
        await click(pub)
        time.sleep(6)
        await cmd("Page.reload")
        time.sleep(8)
        have = " ".join(v for _, v in (await js(INPUTS) or []))
        ok = [t for t, u in todo if u.rstrip("/").lower() in have.lower()]
        return f"{cid}: added {', '.join(ok) or 'nothing'}" + (f"; NOT saved: {[t for t, _ in todo if t not in ok]}"
                                                                if len(ok) < len(todo) else "")


async def main():
    for cid in sys.argv[1:]:
        try:
            print(await run(cid), flush=True)
        except Exception as e:  # noqa: BLE001 - one channel must not stop the rest
            print(f"{cid}: {type(e).__name__}: {e}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
