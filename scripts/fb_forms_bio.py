"""Set the current v3 Facebook bio (brand_art.BIOS) on every open 'Create a Page' form. python -m scripts.fb_forms_bio"""
import asyncio
import json
import sys
import urllib.request

from engine import brand_art
from engine.config import channels
from engine.cr_footage import _eval
from scripts.fb_page_fill import SET

by_name = {c["name"]: c["id"] for c in channels()}
for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read()):
    if t["type"] != "page" or "pages/creation" not in t["url"]:
        continue
    name = asyncio.run(_eval(t["webSocketDebuggerUrl"], '(() => { const e = [...document.querySelectorAll("input")]'
                             '.find(x => (x.closest("label") ? x.closest("label").innerText : "").startsWith("Page name"));'
                             ' return e ? e.value : ""; })()'))
    cid = by_name.get(name or "")
    if not cid:
        continue
    bio = brand_art.BIOS[cid][1]
    ok = asyncio.run(_eval(t["webSocketDebuggerUrl"], SET % (json.dumps("Bio"), json.dumps(bio))))
    sys.stdout.buffer.write(f"{name}: {'bio set' if ok else 'FAILED'} -> {bio}\n".encode("utf-8"))
