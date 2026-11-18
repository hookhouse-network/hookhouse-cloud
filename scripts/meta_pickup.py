"""After the owner approved Meta in Graph API Explorer (visible HookHouse Chrome): read the token from the page (never
printed), connect every channel (setup_steps.meta_connect), check the granted permissions, and send the new login
files to the cloud's secrets inbox. python -m scripts.meta_pickup"""
import asyncio
import json
import urllib.request

import requests
from dotenv import load_dotenv

load_dotenv()
from engine import setup_steps  # noqa: E402
from engine.cr_footage import _eval  # noqa: E402
from engine.publish import GRAPH  # noqa: E402

NEED = {"pages_show_list", "pages_read_engagement", "pages_manage_posts", "instagram_basic",
        "instagram_content_publish", "instagram_manage_insights", "read_insights"}

tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
           if t["type"] == "page" and "tools/explorer" in t["url"])
token = asyncio.run(_eval(tab["webSocketDebuggerUrl"],
                          '(() => { const i = [...document.querySelectorAll("input,textarea")].find(e => '
                          '/^EAA/.test(e.value || "")); return i ? i.value : ""; })()')) or ""
if not token.startswith("EAA"):
    raise SystemExit("No token on the Explorer page yet (finish the Meta popup first).")
perms = requests.get(f"{GRAPH}/me/permissions", params={"access_token": token}, timeout=30).json().get("data", [])
granted = {p["permission"] for p in perms if p.get("status") == "granted"}
print("granted:", sorted(granted))
print("still missing:", sorted(NEED - granted) or "none")
for line in setup_steps.meta_connect(token):
    print(" ", line)
from engine.cloud import state  # noqa: E402
from engine.cloud.store import Store  # noqa: E402
from engine.config import ROOT  # noqa: E402
names = sorted(p.name for p in (ROOT / "data" / "secrets").glob("meta_*.json"))
print("sent to the cloud inbox:", state.send_secrets(Store(), names), "login file(s)")
