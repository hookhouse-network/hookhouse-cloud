"""Read-only look at the visible HookHouse Chrome tab (port 9333): URL (tokens hidden) + page text.
python -m scripts.cdp_peek [chars]"""
import asyncio
import json
import re
import sys
import urllib.request

from engine.cr_footage import _eval

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
tabs = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read()) if t["type"] == "page"]
t = tabs[0]
print(re.sub(r"(access_token=)[^&#]+", r"\1<hidden>", t["url"])[:150])
txt = asyncio.run(_eval(t["webSocketDebuggerUrl"], "document.body.innerText")) or ""
txt = re.sub(r"\bEAA[A-Za-z0-9]{20,}", "<token hidden>", txt)
sys.stdout.buffer.write(txt[:n].encode("utf-8", "replace") + b"\n")
