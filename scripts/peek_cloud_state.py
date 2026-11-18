"""Read-only look at the cloud memory bundle: unpacks a copy into a temp folder (never into the project) and prints
what analytics data exists. Usage: python -m scripts.peek_cloud_state [dest_dir]"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from engine.config import ROOT

load_dotenv(ROOT / ".env")
from engine.cloud import state  # noqa: E402
from engine.cloud.store import Store  # noqa: E402

dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="hh_state_"))
n = state.pull(Store(), root=dest)
print("unpacked", n, "files into", dest)
db = dest / "data" / "analytics.db"
if db.exists():
    c = sqlite3.connect(db)
    for (t,) in c.execute("select name from sqlite_master where type='table'"):
        print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
    print(c.execute("select platform, channel, count(distinct item_id), max(views) from video_metrics "
                    "group by platform, channel").fetchall())
log = dest / "data" / "publish_log.jsonl"
if log.exists():
    rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    print("publish log rows:", len(rows), "keys:", sorted(rows[-1].keys()) if rows else None)
