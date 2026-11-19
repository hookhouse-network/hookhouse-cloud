"""Read-only: the token shown in Graph API Explorer (visible HookHouse Chrome) -> when Meta issued it, whether it is
still valid, and which permissions are granted / missing. The token is never printed. python -m scripts.meta_token_check"""
import asyncio
import json
import time
import urllib.request

import requests

from engine.publish import GRAPH

NEED = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "pages_manage_metadata", "instagram_basic",
        "instagram_content_publish", "instagram_manage_insights", "instagram_manage_comments", "read_insights",
        "business_management"]


async def token() -> str:
    import websockets
    tab = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json/list").read())
               if t["type"] == "page" and "tools/explorer" in t["url"])
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": (
            '([...document.querySelectorAll("input")].find(x => /^EAA/.test(x.value)) || {}).value || ""'),
            "returnByValue": True}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                return m["result"]["result"].get("value") or ""


def main():
    tok = asyncio.run(token())
    if not tok:
        print("no token on the page")
        return
    d = requests.get(f"{GRAPH}/debug_token", params={"input_token": tok, "access_token": tok}, timeout=30).json()
    info = d.get("data") or {}
    issued = info.get("issued_at")
    age = f"{(time.time() - issued) / 60:.0f} min ago" if issued else "unknown"
    print(f"valid: {info.get('is_valid')} | issued: {age} | app: {info.get('application')}")
    p = requests.get(f"{GRAPH}/me/permissions", params={"access_token": tok}, timeout=30).json().get("data") or []
    granted = {x["permission"] for x in p if x.get("status") == "granted"}
    print("missing:", [x for x in NEED if x not in granted] or "none")
    acc = requests.get(f"{GRAPH}/me/accounts", params={"access_token": tok, "limit": 50,
                                                       "fields": "name,instagram_business_account{username}"},
                       timeout=30).json().get("data") or []
    print(f"pages visible: {len(acc)}")
    for a in acc:
        print(f"  {a['name']}: IG {(a.get('instagram_business_account') or {}).get('username') or '-'}")


if __name__ == "__main__":
    main()
