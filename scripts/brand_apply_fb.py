"""Put the v2 branding on every connected Facebook Page: profile picture, cover, short bio (About).
Pictures are uploaded to the Page unpublished (no post in the feed), then set as profile picture / cover.
python -m scripts.brand_apply_fb [channel_id ...]"""
import json
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
from engine import brand_art  # noqa: E402
from engine.config import ROOT  # noqa: E402
from engine.publish import GRAPH  # noqa: E402

only = set(sys.argv[1:])
for f in sorted((ROOT / "data" / "secrets").glob("meta_*.json")):
    cid = f.stem[5:]
    if only and cid not in only:
        continue
    c = json.loads(f.read_text(encoding="utf-8"))
    page, tok = c.get("page_id"), c.get("page_token")
    if not (page and tok):
        print(f"{cid}: no Facebook Page connected")
        continue
    files = brand_art.OUT / cid
    v2 = (files / "scene.png").exists()                  # only the v2 artwork goes up (never the old text logos)
    res = [] if v2 else ["pictures: waiting for the new artwork"]

    def upload(path):
        with open(path, "rb") as fh:
            r = requests.post(f"{GRAPH}/{page}/photos", data={"published": "false", "access_token": tok},
                              files={"source": (path.name, fh)}, timeout=120).json()
        return r.get("id"), r

    if v2 and (files / "avatar.png").exists():
        pid, r = upload(files / "avatar.png")
        img = requests.get(f"{GRAPH}/{pid}", params={"fields": "images", "access_token": tok}, timeout=30).json() \
            if pid else {}
        url = max(img.get("images") or [{}], key=lambda x: x.get("width", 0)).get("source")
        rp = requests.post(f"{GRAPH}/{page}/picture", data={"picture": url, "access_token": tok}, timeout=60).json() \
            if url else r
        res.append("picture " + ("ok" if rp.get("success") or rp.get("id") else str(rp.get("error", rp))[:80]))
    if v2 and (files / "facebook_cover.jpg").exists():
        pid, r = upload(files / "facebook_cover.jpg")
        rc = requests.post(f"{GRAPH}/{page}", data={"cover": pid, "no_feed_story": "true", "access_token": tok},
                           timeout=60).json() if pid else r
        res.append("cover " + ("ok" if rc.get("success") else str(rc.get("error", rc))[:80]))
    bio = (brand_art.BIOS.get(cid) or ("", ""))[1]
    from engine.config import channel
    from engine.links import data as links
    ch = channel(cid)
    yt = ((links().get(cid) or {}).get("youtube") or (ch.get("handles") or {}).get("youtube") or "").lstrip("@")
    fields = {"about": bio, "description": brand_art.fb_description(cid, str(ch.get("about") or ""))}
    if yt:
        fields["website"] = f"https://www.youtube.com/@{yt}"
    for k, v in fields.items():
        if not v:
            continue
        rb = requests.post(f"{GRAPH}/{page}", data={k: v, "access_token": tok}, timeout=30).json()
        res.append(f"{k} " + ("ok" if rb.get("success") else str(rb.get("error", rb))[:80]))
    print(f"{cid}: " + ", ".join(res))
