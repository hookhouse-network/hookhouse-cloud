"""Audit the cloud publish log: repeated uploads (same title / same item posted more than once), posts per channel.
python -m scripts.audit_uploads <unpacked state dir>"""
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

root = Path(sys.argv[1])
rows = [json.loads(ln) for ln in (root / "data" / "publish_log.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
print("rows:", len(rows), "from", time.strftime("%d %b %H:%M", time.localtime(rows[0]["at"])),
      "to", time.strftime("%d %b %H:%M", time.localtime(rows[-1]["at"])))
ups = [r for r in rows if r.get("done") and (r.get("result") or {}).get("video_id") and r["platform"] == "youtube"]
print("\nYouTube uploads done:", len(ups))
by_title = defaultdict(list)
by_item = defaultdict(list)
for r in ups:
    t = (r.get("details") or {}).get("title") or r.get("what")
    by_title[(r["channel"], t)].append(r)
    by_item[r.get("item_id")].append(r)
for (ch, t), rs in sorted(by_title.items(), key=lambda kv: -len(kv[1])):
    flag = "  <-- REPEATED" if len(rs) > 1 else ""
    print(f"{len(rs)}x {ch:22} {str(t)[:60]:60} " +
          ", ".join(time.strftime("%d %b %H:%M", time.localtime(r["at"])) + " " + r["result"]["video_id"] for r in rs) + flag)
print("\nsame plan item uploaded more than once:")
for it, rs in by_item.items():
    if it and len(rs) > 1:
        print(" ", it, [(r["channel"], r["result"]["video_id"]) for r in rs])
print("\nall platforms, done per channel:")
c = Counter((r["channel"], r["platform"]) for r in rows if r.get("done"))
for (ch, p), n in sorted(c.items()):
    print(f"  {ch:22} {p:12} {n}")
other = Counter((r["platform"], str((r.get("result") or {}).get("error"))[:90]) for r in rows
                if not r.get("done") and (r.get("result") or {}).get("error"))
print("\nerrors:")
for (p, e), n in other.most_common(15):
    print(f"  {n}x {p}: {e}")
