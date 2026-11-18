"""List each connected channel's real YouTube uploads (read-only) and flag repeated titles.
python -m scripts.yt_uploads"""
import time
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()
from engine import publish  # noqa: E402
from engine.config import channels  # noqa: E402

API = "https://www.googleapis.com/youtube/v3"
for ch in channels():
    tok = publish.yt_access_token(ch["id"])
    if not tok:
        print(f"{ch['id']:24} not connected")
        continue
    h = {"Authorization": f"Bearer {tok}"}
    me = requests.get(f"{API}/channels", params={"part": "contentDetails,statistics", "mine": "true"}, headers=h,
                      timeout=30).json()
    if not me.get("items"):
        print(f"{ch['id']:24} no channel: {str(me)[:120]}")
        continue
    up = me["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    st = me["items"][0]["statistics"]
    vids, page = [], None
    while True:
        r = requests.get(f"{API}/playlistItems", params={"part": "snippet,status", "playlistId": up, "maxResults": 50,
                                                          **({"pageToken": page} if page else {})}, headers=h, timeout=30).json()
        vids += r.get("items", [])
        page = r.get("nextPageToken")
        if not page or len(vids) >= 200:
            break
    titles = Counter(v["snippet"]["title"] for v in vids)
    print(f"{ch['id']:24} {len(vids)} uploads, {st.get('subscriberCount')} subs, {st.get('viewCount')} views")
    for v in vids[:12]:
        s = v["snippet"]
        flag = "  <-- SAME TITLE x%d" % titles[s["title"]] if titles[s["title"]] > 1 else ""
        print(f"    {s['publishedAt'][:16]} {v['status'].get('privacyStatus', ''):8} {s['resourceId']['videoId']} "
              f"{s['title'][:60]}{flag}")
    time.sleep(0.2)
