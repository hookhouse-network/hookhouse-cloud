"""Read-only: the status of every picked campaign on Content Rewards (joined? footage? ended?) via the PC's Chrome.
python -m scripts.campaign_status"""
from engine import cr_footage, db

conn = db.connect()
rows = {c["id"]: c for s in ("picked", "joined") for c in db.list_campaigns(conn, s)}
for c in cr_footage.watched():
    rows.setdefault(c["id"], c)
print("chrome up:", cr_footage.chrome_up(), "| campaigns picked/joined:", len(rows))
for c in rows.values():
    if "contentrewards.com" not in str(c.get("url")):
        print(f"  {c.get('name', c['id'])[:45]:45} (not a Content Rewards page: {str(c.get('url'))[:50]})")
        continue
    try:
        r = cr_footage.check(c)
    except Exception as e:  # noqa: BLE001
        r = {"error": f"{type(e).__name__}: {e}"}
    state = r.get("error") or ("ENDED" if r.get("ended") else "JOINED" if r.get("joined") else "not joined yet")
    print(f"  {c.get('name', c['id'])[:45]:45} {state:30} footage links: {len(r.get('files') or [])}")
