"""Real video footage from free sources that allow reuse (documentary B-roll).

Allowed: NASA (US government, generally no copyright; no NASA logos / no endorsement implied),
Wikimedia Commons video (public domain / CC0 / CC BY only), Internet Archive films marked
public domain (e.g. Prelinger), Pexels and Pixabay videos (free licenses, keys optional).
NOT allowed: documentaries that are only "free to watch" (YouTube, Netflix, BBC, NatGeo...).

Only the few seconds we need are downloaded (ffmpeg reads the part of the file it needs).
"""
from __future__ import annotations

import hashlib
import re
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import requests

from ..config import ROOT
from . import ffmpeg
from .visuals import UA, _get, _strip_html, license_ok, session

CACHE = ROOT / "data" / "cache" / "footage"

# Talking heads, politicians, logos and burned-in subtitles look bad and raise rights questions.
SKIP = re.compile(r"(remarks|press|briefing|conference|interview|speech|speaks|talks|statement|podcast|"
                  r"president|senator|minister|administrator|town hall|q&a|webinar|lecture|panel|"
                  r"anniversary|coin|logo|trailer|ceremony|award|hoax|update)", re.I)


def usable(f: "Footage") -> bool:
    return not SKIP.search(f.title or "")


@dataclass
class Footage:
    url: str
    source: str
    title: str
    credit: str
    license: str
    text: str                               # used to match it with the scene
    duration: float = 0.0
    meta: dict = field(default_factory=dict)


def nasa(query: str, limit: int = 8) -> list[Footage]:
    """Search only; the video file list is fetched later, just for the clip we pick."""
    try:
        data = _get("https://images-api.nasa.gov/search", params={"q": query, "media_type": "video"},
                    timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for item in data.get("collection", {}).get("items", [])[:limit]:
        d = (item.get("data") or [{}])[0]
        if not item.get("href"):
            continue
        title = d.get("title", "")
        out.append(Footage(item["href"], "nasa", title, f'"{title}" — NASA ({d.get("center", "NASA")})',
                           "Public domain (NASA)",
                           f"{title}. {(d.get('description') or '')[:300]} {' '.join(d.get('keywords', [])[:8])}"))
    return out


def _nasa_mp4(collection_url: str) -> str | None:
    try:
        assets = _get(collection_url, timeout=30).json()
    except (requests.RequestException, ValueError):
        return None
    mp4s = [a for a in assets if isinstance(a, str) and a.endswith(".mp4")]
    pick = next((a for key in ("~large.mp4", "~medium.mp4", "~orig.mp4", "~mobile.mp4")
                 for a in mp4s if a.endswith(key)), None)
    return pick.replace("http://", "https://") if pick else None


def wikimedia_video(query: str, limit: int = 8) -> list[Footage]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{query} filetype:video", "gsrlimit": limit, "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata"}
    try:
        data = _get("https://commons.wikimedia.org/w/api.php", params=params, timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not license_ok(lic) or info.get("height", 0) < 360:
            continue
        title = page.get("title", "").removeprefix("File:")
        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown"
        desc = _strip_html(meta.get("ImageDescription", {}).get("value", ""))[:300]
        out.append(Footage(info["url"], "wikimedia", title, f'"{title}" by {artist} ({lic}), Wikimedia Commons',
                           lic, f"{Path(title).stem} {desc}", float(info.get("duration") or 0)))
    return out


def archive_pd(query: str, limit: int = 5) -> list[Footage]:
    """Internet Archive films marked Public Domain — curated collections only, because anyone can
    label their own upload "public domain" (we found a pirated TV recording labelled that way)."""
    q = f'({query}) AND mediatype:movies AND collection:(prelinger OR fedflix) AND licenseurl:(*publicdomain*)'
    try:
        data = _get("https://archive.org/advancedsearch.php",
                    params={"q": q, "fl[]": ["identifier", "title", "description", "licenseurl"],
                            "rows": limit, "output": "json"}, timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for doc in data.get("response", {}).get("docs", []):
        ident = doc["identifier"]
        title = doc.get("title", ident)
        desc = doc.get("description", "")
        desc = " ".join(desc) if isinstance(desc, list) else desc
        # url stays "ia:<id>" until this film is picked; the file list is fetched only then (fast search)
        out.append(Footage(f"ia:{ident}", "internet_archive", title,
                           f'"{title}" — Internet Archive (Public Domain)', "Public domain",
                           f"{title}. {_strip_html(desc)[:300]}", 0.0,
                           {"page": f"https://archive.org/details/{ident}"}))
    return out


def _archive_mp4(ident: str) -> tuple[str, float] | None:
    try:
        files = _get(f"https://archive.org/metadata/{ident}/files", timeout=20).json().get("result", [])
    except (requests.RequestException, ValueError):
        return None
    mp4s = [f for f in files if f.get("name", "").endswith(".mp4")]
    if not mp4s:
        return None
    best = max(mp4s, key=lambda f: (int(f.get("height") or 0), int(f.get("size") or 0)))
    return f"https://archive.org/download/{ident}/{best['name']}", float(best.get("length") or 0)


def pexels_video(query: str, orientation: str = "portrait", limit: int = 5) -> list[Footage]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    try:
        data = session().get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                            params={"query": query, "orientation": orientation, "per_page": limit},
                            timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for v in data.get("videos", []):
        files = sorted([f for f in v.get("video_files", []) if f.get("height")], key=lambda f: f["height"])
        good = [f for f in files if f["height"] >= 1080] or files
        if not good:
            continue
        slug = v.get("url", "").rstrip("/").split("/")[-1].rsplit("-", 1)[0].replace("-", " ")
        out.append(Footage(good[0]["link"], "pexels", slug, f"Video by {v.get('user', {}).get('name', 'Unknown')} on Pexels",
                           "Pexels License", slug or query, float(v.get("duration") or 0)))
    return out


def pixabay_video(query: str, limit: int = 5) -> list[Footage]:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    try:
        data = session().get("https://pixabay.com/api/videos/", params={"key": key, "q": query, "per_page": limit},
                            timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for h in data.get("hits", []):
        v = h.get("videos", {})
        f = v.get("large") if v.get("large", {}).get("url") else v.get("medium", {})
        if not f.get("url"):
            continue
        out.append(Footage(f["url"], "pixabay", h.get("tags", query), f"Video by {h.get('user', 'Unknown')} on Pixabay",
                           "Pixabay Content License", h.get("tags", query), float(h.get("duration") or 0)))
    return out


def search(query: str, orientation: str = "portrait") -> list[Footage]:
    from concurrent.futures import ThreadPoolExecutor
    jobs = [lambda: nasa(query), lambda: wikimedia_video(query), lambda: pexels_video(query, orientation),
            lambda: pixabay_video(query), lambda: archive_pd(query)]
    with ThreadPoolExecutor(5) as pool:
        return [f for part in pool.map(lambda j: j(), jobs) for f in part if usable(f)]


def _probe_duration(url: str) -> float:
    try:
        out = subprocess.run([ffmpeg.ffprobe_bin(), "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", "-user_agent", UA["User-Agent"], url],
                             capture_output=True, text=True, timeout=20)
        return float(out.stdout.strip() or 0)
    except (subprocess.SubprocessError, ValueError):
        return 0.0


def fetch_segment(f: Footage, seconds: float, at: float | None = None) -> Path | None:
    """Download only `seconds` of the clip (from ~30% in, skipping intros/logos)."""
    if f.source == "nasa" and f.url.endswith(".json"):
        mp4 = _nasa_mp4(f.url)
        if not mp4:
            return None
        f.url = mp4
    if f.url.startswith("ia:"):
        got = _archive_mp4(f.url[3:])
        if not got:
            return None
        f.url, f.duration = got
    total = f.duration or _probe_duration(f.url)
    if total and total < seconds + 0.5:
        at = 0.0
    elif at is None:
        at = max(0.0, total * 0.3) if total else 3.0
    key = hashlib.md5(f"{f.url}|{at:.1f}|{seconds:.1f}".encode()).hexdigest()
    dest = CACHE / f"{key}.mp4"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        ffmpeg.run(["-user_agent", UA["User-Agent"], "-rw_timeout", "20000000", "-ss", f"{at:.2f}",
                    "-t", f"{seconds:.2f}", "-i", f.url, "-vf", "scale=-2:'min(1080,ih)',fps=30", "-an",
                    *ffmpeg.H264_FAST, dest], retries=0, timeout=75)
    except RuntimeError:
        return None
    return dest if dest.exists() and dest.stat().st_size > 10_000 else None
