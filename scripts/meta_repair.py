"""18 Nov: keep each channel's Instagram account id (Meta didn't show the IG link for some Pages, and meta_connect
saved them without it), put the new full-permission user token in every Meta login file, test Instagram insights and
the Page, then send the files to the cloud inbox. Nothing secret is printed. python -m scripts.meta_repair <old dir>"""
import json
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
from engine.config import ROOT  # noqa: E402
from engine.publish import GRAPH  # noqa: E402

old_dir = Path(sys.argv[1])
sec = ROOT / "data" / "secrets"
new_token = json.loads((sec / "meta_hot_take_hq.json").read_text(encoding="utf-8"))["access_token"]   # fresh one
names = []
for f in sorted(sec.glob("meta_*.json")):
    cur = json.loads(f.read_text(encoding="utf-8"))
    old = json.loads((old_dir / f.name).read_text(encoding="utf-8")) if (old_dir / f.name).exists() else {}
    if not cur.get("ig_user_id") and old.get("ig_user_id"):
        cur["ig_user_id"] = old["ig_user_id"]
    cur["access_token"] = new_token
    cur.setdefault("login", "facebook")
    f.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    ig = cur.get("ig_user_id")
    r = requests.get(f"{GRAPH}/{ig}", params={"fields": "username,media_count", "access_token": new_token},
                     timeout=30).json() if ig else {"error": {"message": "no Instagram id"}}
    media = requests.get(f"{GRAPH}/{ig}/media", params={"limit": 1, "access_token": new_token}, timeout=30).json() \
        if ig else {}
    mid = ((media.get("data") or [{}])[0]).get("id")
    ins = requests.get(f"{GRAPH}/{mid}/insights", params={"metric": "views,reach", "access_token": new_token},
                       timeout=30).json() if mid else {}
    page = cur.get("page_id")
    pg = requests.get(f"{GRAPH}/{page}", params={"fields": "name", "access_token": cur.get("page_token") or new_token},
                      timeout=30).json() if page else {}
    print(f"{f.stem[5:]:22} IG @{r.get('username') or '-'} ({r.get('error', {}).get('message', 'ok')[:50]})"
          f" | stats: {'ok' if ins.get('data') else (ins.get('error', {}).get('message', 'no post yet')[:60])}"
          f" | FB Page: {pg.get('name') or pg.get('error', {}).get('message', 'none')[:40]}")
    names.append(f.name)
from engine.cloud import state  # noqa: E402
from engine.cloud.store import Store  # noqa: E402
print("sent to the cloud inbox:", state.send_secrets(Store(), names), "login file(s)")
