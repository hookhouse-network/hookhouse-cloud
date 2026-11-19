"""Create a YouTube channel (Brand Account) in the signed-in HookHouse Chrome (owner 20 Nov: "do all the steps by
yourself"). python -m scripts.yt_create_channel "<name>" [handle]   -- e.g. "Stream Clips" StreamClipsDaily
Headless; reports each screen. Stops on any screen it does not recognise (never types personal data)."""
import asyncio
import json
import sys

from engine.kick import _Tab

DEEP = r"""(() => { const all = []; const walk = r => r.querySelectorAll('*').forEach(e => { all.push(e);
  if (e.shadowRoot) walk(e.shadowRoot); }); walk(document); return all; })()"""


def say(m: str) -> None:
    sys.stdout.buffer.write((m + "\n").encode("utf-8"))
    sys.stdout.flush()


async def click_deep(tab, *labels) -> bool:
    want = json.dumps([x.lower() for x in labels])
    xy = await tab.js(f"""(() => {{ const want = {want}; const all = {DEEP};
      const el = all.find(e => {{ const t = ((e.innerText || '').trim() || e.getAttribute('aria-label') || '').trim().toLowerCase();
        const r = e.getBoundingClientRect(); return want.includes(t) && r.width > 0 && r.height > 0
          && /^(BUTTON|A|TP-YT-PAPER-ITEM|YT-BUTTON-SHAPE|TP-YT-PAPER-BUTTON|YTD-BUTTON-RENDERER|DIV|SPAN)$/.test(e.tagName); }});
      if (!el) return null; const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
    if not xy:
        return False
    for k in ("mouseMoved", "mousePressed", "mouseReleased"):
        await tab.cmd("Input.dispatchMouseEvent", {"type": k, "x": xy[0], "y": xy[1], "button": "left", "clickCount": 1})
    return True


async def dialog_text(tab) -> str:
    return await tab.js(f"""(() => {{ const all = {DEEP}; const d = all.filter(e => /DIALOG|tp-yt-paper-dialog/i.test(e.tagName)
      || e.getAttribute('role') === 'dialog').filter(e => e.getBoundingClientRect().width > 0);
      return d.map(x => x.innerText).join(' || ').slice(0, 800); }})()""") or ""


async def fill_deep(tab, label_rx: str, value: str) -> bool:
    ok = await tab.js(f"""(() => {{ const all = {DEEP}; const rx = new RegExp({json.dumps(label_rx)}, 'i');
      const inp = all.filter(e => e.tagName === 'INPUT' && e.getBoundingClientRect().width > 0)
        .find(e => rx.test((e.getAttribute('aria-label') || '') + ' ' + (e.placeholder || '') + ' ' + (e.id || '')
          + ' ' + ((e.closest('[label]') || {{}}).getAttribute ? (e.closest('[label]').getAttribute('label') || '') : '')));
      if (!inp) return false; inp.focus(); inp.select && inp.select(); return true; }})()""")
    if not ok:
        return False
    await tab.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2,
                                             "commands": ["selectAll"]})
    await tab.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2})
    await tab.cmd("Input.insertText", {"text": value})
    return True


async def fill_nth(tab, n: int, value: str) -> bool:
    """The create dialog's boxes have no labels: visible text inputs other than search, in order (Name, Handle)."""
    ok = await tab.js(f"""(() => {{ const ins = {DEEP}.filter(e => e.tagName === 'INPUT' && e.type === 'text'
      && e.name !== 'search_query' && e.getBoundingClientRect().width > 0); const e = ins[{n}];
      if (!e) return false; e.focus(); return true; }})()""")
    if not ok:
        return False
    await tab.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2,
                                             "commands": ["selectAll"]})
    await tab.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2})
    await tab.cmd("Input.insertText", {"text": value})
    return True


async def main(name: str, handle: str | None) -> None:
    async with _Tab("https://www.youtube.com/channel_switcher") as tab:
        await asyncio.sleep(12)
        if name.lower() in (await tab.js("document.body.innerText") or "").lower():
            say(f"a channel called {name} already exists")
            return
        if not await click_deep(tab, "Create a channel"):
            say("no 'Create a channel' button")
            return
        await asyncio.sleep(6)
        say("screen 1: " + (await dialog_text(tab))[:400].replace("\n", " / "))
        if not await fill_nth(tab, 0, name):
            say("no name field; url: " + str(await tab.js("location.href")))
            return
        await asyncio.sleep(3)
        if handle:
            await fill_nth(tab, 1, handle)
            await asyncio.sleep(5)
        say("filled: " + (await dialog_text(tab))[:500].replace("\n", " / "))
        if not await click_deep(tab, "Create channel"):
            say("no Create button")
            return
        await asyncio.sleep(15)
        say("after create: url " + str(await tab.js("location.href")) + " | " +
            ((await dialog_text(tab)) or (await tab.js("document.body.innerText") or "")[:300]).replace("\n", " / ")[:400])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
