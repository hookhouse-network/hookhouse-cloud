"""Undo for Instagram: channels whose Instagram the NEW token cannot see keep their OLD token for Instagram
(access_token); the new Page token stays for Facebook posting. Tests each, resends to the cloud inbox.
python -m scripts.meta_keep_old_ig <old secrets dir>"""
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
names = []
for f in sorted(sec.glob("meta_*.json")):
    cur = json.loads(f.read_text(encoding="utf-8"))
    old = json.loads((old_dir / f.name).read_text(encoding="utf-8")) if (old_dir / f.name).exists() else {}
    ig = cur.get("ig_user_id")

    def sees(tok):
        return bool(ig and tok and requests.get(f"{GRAPH}/{ig}", params={"fields": "username", "access_token": tok},
                                                timeout=30).json().get("username"))
    if not sees(cur.get("access_token")) and sees(old.get("access_token")):
        cur["access_token"] = old["access_token"]
        if old.get("expires_at"):
            cur["expires_at"] = old["expires_at"]
        f.write_text(json.dumps(cur, indent=1), encoding="utf-8")
        state = "old token kept for Instagram"
    else:
        state = "new token"
    print(f"{f.stem[5:]:22} Instagram reachable: {sees(cur.get('access_token'))} ({state}) | "
          f"FB Page token: {bool(cur.get('page_token'))}")
    names.append(f.name)
from engine.cloud import state as st  # noqa: E402
from engine.cloud.store import Store  # noqa: E402
print("sent to the cloud inbox:", st.send_secrets(Store(), names), "login file(s)")
