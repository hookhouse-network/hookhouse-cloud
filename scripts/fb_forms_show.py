"""Show name / category / bio of every open 'Create a Page' form. python -m scripts.fb_forms_show"""
import asyncio
import json
import sys
import urllib.request

from engine.cr_footage import _eval

JS = r'''JSON.stringify([...document.querySelectorAll("input,textarea")].map(e => {
  const l = e.closest("label"); return [l ? l.innerText.split("\n")[0].slice(0, 16) : "", e.value];
}).filter(x => x[0] && x[1]))'''
for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read()):
    if t["type"] == "page" and "pages/creation" in t["url"]:
        v = asyncio.run(_eval(t["webSocketDebuggerUrl"], JS)) or "[]"
        sys.stdout.buffer.write((v + "\n").encode("utf-8"))
