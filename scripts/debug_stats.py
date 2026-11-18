"""Dry diagnosis of the stats fetch against an unpacked state copy (nothing is written to the project or the cloud).
Usage: python -m scripts.debug_stats <state_copy_dir>"""
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from engine.config import ROOT

load_dotenv(ROOT / ".env")
copy = Path(sys.argv[1])
import engine.publish as publish  # noqa: E402
import engine.stats_fetch as sf  # noqa: E402

publish.LOG = sf.LOG = copy / "data" / "publish_log.jsonl"
publish.SECRETS = sf.SECRETS = copy / "data" / "secrets"
import engine.connect as connect  # noqa: E402

for name in ("SECRETS", "SECRET_DIR", "TOKENS"):
    if hasattr(connect, name):
        setattr(connect, name, copy / "data" / "secrets")
vids = sf.posted_videos()
print(len(vids), "posted videos found")
import requests  # noqa: E402

for v in vids[:40]:
    h = (time.time() - v["posted_at"]) / 3600
    try:
        m = (sf._youtube if v["platform"] == "youtube" else sf._instagram)(v, requests)
    except Exception as e:  # noqa: BLE001
        m = f"ERROR {type(e).__name__}: {str(e)[:160]}"
    print(f"{v['platform']:9} {v['channel']:22} {v['id']:14} {h:6.0f}h bucket={sf.due_bucket(h)} -> {m}")
