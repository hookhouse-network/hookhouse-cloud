"""Finds images for story scenes, safely.

Order: AI image (if available) -> Wikimedia Commons (public domain / CC0 / CC BY only)
-> Pexels (free license) -> generated title card (always works).
Every image's credit is recorded for the video description.
"""
from __future__ import annotations

import base64
import hashlib
import html
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import ROOT, load_env
from .fonts import font_file

# Wikimedia asks automated tools to identify themselves with a contact link.
# Set CONTACT_URL in .env (e.g. your private GitHub repo page). Never put a personal email here.
load_env()                                     # CONTACT_URL must be known before the User-Agent is built
UA = {"User-Agent": f"ClipFactory/0.2 ({os.environ.get('CONTACT_URL', 'personal video project')}) python-requests"}


_PAUSED_UNTIL: dict[str, float] = {}     # host -> time when we may ask again
_LAST_CALL: dict[str, float] = {}
_GAP_S = {"upload.wikimedia.org": 1.0, "commons.wikimedia.org": 1.0}   # polite spacing per host


class RateLimited(requests.RequestException):
    pass


_SESSION: requests.Session | None = None


def session() -> requests.Session:
    """One kept-alive connection pool for all picture/footage requests."""
    global _SESSION
    if _SESSION is None:
        import requests.adapters
        _SESSION = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        _SESSION.mount("https://", adapter)
        _SESSION.mount("http://", adapter)
    return _SESSION


def _get(url: str, **kwargs) -> requests.Response:
    """GET that respects 'too many requests' (HTTP 429). Waits up to 90 s are honoured and retried (skipping them
    made every picture search silently empty -> a video full of text cards); a long pause (Wikimedia sends
    Retry-After: 600) is remembered and later calls to that host fail fast."""
    import time
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    headers, timeout = kwargs.pop("headers", UA), kwargs.pop("timeout", 60)
    for attempt in range(3):
        if time.time() < _PAUSED_UNTIL.get(host, 0):
            raise RateLimited(f"{host} asked us to wait; skipping for now")
        wait = _GAP_S.get(host, 0) - (time.time() - _LAST_CALL.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[host] = time.time()
        r = session().get(url, headers=headers, timeout=timeout, **kwargs)
        if r.status_code != 429:
            return r
        try:
            retry = int(r.headers.get("Retry-After", 5))
        except ValueError:
            retry = 60
        if retry > 90 or attempt == 2:
            _PAUSED_UNTIL[host] = time.time() + retry
            raise RateLimited(f"{host} rate limit: pause {retry}s")
        time.sleep(retry)
    return r
CACHE = ROOT / "data" / "cache" / "images"

# Share-alike (BY-SA) and non-commercial (NC) licenses are excluded on purpose.
SAFE_LICENSE = re.compile(r"^(public domain|pd\b|pd-|cc0|cc by \d|cc-by-\d|cc by$|attribution$)", re.I)
UNSAFE = re.compile(r"(\bsa\b|-sa|share|nc|non-?commercial|nd|fair use|all rights)", re.I)


NOT_A_SCENE = re.compile(r"(chart|graph|plot|diagram|statistic|career|performance|logo|signature|autograph|"
                         r"stamp|postage|philatel|banknote|propaganda|screenshot|screen shot|website|webpage|user interface|"
                         r"icon|coat of arms|flag of|seal of|\.svg|scorecard|table|timeline|infographic)")


@dataclass
class Visual:
    path: Path
    source: str
    credit: str = ""
    license: str = ""
    meta: dict = field(default_factory=dict)


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _download(url: str, dest: Path, max_mb: int = 25) -> Path:
    """Download once (cached). Files over max_mb are skipped (huge archive scans)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        r = _get(url, stream=True)
        r.raise_for_status()
        if int(r.headers.get("Content-Length") or 0) > max_mb * 1024 * 1024:
            raise requests.RequestException(f"file too large: {url}")
        data, size = bytearray(), 0
        for chunk in r.iter_content(1 << 16):
            data += chunk
            size += len(chunk)
            if size > max_mb * 1024 * 1024:
                raise requests.RequestException(f"file too large: {url}")
        dest.write_bytes(bytes(data))
    return dest


def license_ok(short_name: str) -> bool:
    s = (short_name or "").strip()
    return bool(SAFE_LICENSE.search(s)) and not UNSAFE.search(s)


def wikimedia(query: str, limit: int = 8, min_width: int = 900, download: bool = True,
              width: int = 1280) -> list[Visual]:
    """Free-licence photos. download=False returns candidates only (call fetch() on the one you pick).
    width uses Wikimedia's standard thumbnail sizes (1280/1920) — odd sizes get rate-limited."""
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": limit, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": width,
    }
    try:
        data = _get("https://commons.wikimedia.org/w/api.php", params=params, timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    results = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        title_l = page.get("title", "").lower()
        if NOT_A_SCENE.search(title_l):        # charts, logos, signatures... make dull scenes
            continue
        if not license_ok(lic) or info.get("width", 0) < min_width or "image" not in info.get("mime", ""):
            continue
        url = info.get("thumburl") or info.get("url")
        ext = Path(url.split("?")[0]).suffix or ".jpg"
        dest = CACHE / f"wm_{hashlib.md5(url.encode()).hexdigest()}{ext}"
        if download:
            try:
                _download(url, dest)
            except requests.RequestException:
                continue
        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown"
        title = page.get("title", "").removeprefix("File:")
        desc = _strip_html(meta.get("ImageDescription", {}).get("value", ""))[:300]
        results.append(Visual(dest, "wikimedia", f'"{title}" by {artist} ({lic}), Wikimedia Commons', lic,
                              {"page": info.get("descriptionurl"), "text": f"{Path(title).stem} {desc}", "url": url}))
    return results


def fetch(v: Visual) -> Path | None:
    """Download a candidate picked from a download=False search (cached)."""
    if v.path.exists():
        return v.path
    try:
        return _download(v.meta["url"], v.path)
    except (requests.RequestException, KeyError):
        return None


def pexels(query: str, limit: int = 5, download: bool = True) -> list[Visual]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    try:
        data = session().get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                            params={"query": query, "orientation": "portrait", "per_page": limit}, timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for p in data.get("photos", []):
        url = p["src"].get("large2x") or p["src"]["original"]
        dest = CACHE / f"px_{p['id']}.jpg"
        if download:
            try:
                _download(url, dest)
            except requests.RequestException:
                continue
        out.append(Visual(dest, "pexels", f"Photo by {p.get('photographer', 'Unknown')} on Pexels", "Pexels License",
                          {"text": p.get("alt") or query, "url": url}))
    return out


def pixabay(query: str, limit: int = 8, download: bool = True, orientation: str = "vertical") -> list[Visual]:
    """Pixabay photos (Pixabay Content License: free for commercial use, no credit required; we credit anyway).
    19 Nov: the photo fallback only had Wikimedia (no Pexels key), so storyboard videos whose free AI pictures ran out
    found nothing and failed ("15/15 scenes had no picture"). Results are cached; files are downloaded, never hotlinked
    (Pixabay API rule)."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query.strip():
        return []
    try:
        data = session().get("https://pixabay.com/api/", params={
            "key": key, "q": query[:100], "image_type": "photo", "orientation": orientation, "per_page": max(3, limit),
            "safesearch": "true", "min_width": 900}, timeout=30).json()
    except (requests.RequestException, ValueError):
        return []
    out = []
    for h in (data.get("hits") or [])[:limit]:
        url = h.get("largeImageURL") or h.get("webformatURL")
        tags = str(h.get("tags") or "").lower()
        if not url or re.search(r"\bai\b|ai[- ]generated|ai art|midjourney|stable diffusion|wombo", tags):
            continue                                   # real photos only (Pixabay also hosts AI art: slop look)
        dest = CACHE / f"pb_{h['id']}.jpg"
        if download:
            try:
                _download(url, dest)
            except requests.RequestException:
                continue
        out.append(Visual(dest, "pixabay", f"Image by {h.get('user', 'Unknown')} on Pixabay", "Pixabay Content License",
                          {"text": h.get("tags") or query, "url": url}))
    return out


def ai_prompt_key(prompt: str, style: str = "") -> tuple[str, str]:
    """The full prompt sent to FLUX and its file key (shared with the GPU batch worker)."""
    full = f"{prompt}, {style}, cinematic lighting, highly detailed, vertical composition".strip(", ")
    return full, hashlib.md5(full.encode()).hexdigest()


def gpu_jobs_from_script(script: dict, style: str = "") -> list[dict]:
    """AI image jobs for the weekly GPU batch (one per 'ai' scene)."""
    jobs = []
    for sc in script.get("scenes", []):
        if sc.get("visual_type") == "ai":
            full, key = ai_prompt_key(sc.get("ai_prompt") or sc.get("visual_query", ""), style)
            jobs.append({"key": key, "prompt": full})
    return jobs


def ai_image(prompt: str, style: str = "") -> Visual | None:
    """AI image: first look in the weekly GPU batch folder, then Cloudflare's free FLUX."""
    from ..ip_guard import scrub                    # 20 Nov: never draw a copyrighted character (strike risk)
    prompt, _ = scrub(prompt)
    full, key = ai_prompt_key(prompt, style)
    batch = ROOT / "data" / "gpu_batch" / f"{key}.png"
    if batch.exists():
        return Visual(batch, "ai_flux_batch", "AI-generated image", "Own (FLUX.1-schnell, Apache 2.0)")
    acct, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        return None
    from .. import storyboard
    if not storyboard._open("cloudflare"):            # used up today: don't spend a call per scene
        return None
    try:
        r = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {token}"}, json={"prompt": full, "steps": 8}, timeout=120)
        data = r.json()
        img_b64 = (data.get("result") or {}).get("image")
    except (requests.RequestException, ValueError):
        return None
    if r.status_code == 429 or any(e.get("code") == 4006 for e in data.get("errors") or [] if isinstance(e, dict)):
        # 21 Nov: "used up your daily free allocation of 10,000 neurons" was swallowed, so the NoPictures rule never
        # fired and story videos were made with word cards (then held). Mark it; the video waits for the reset.
        storyboard._block("cloudflare")
        print("AI pictures: Cloudflare's free daily allowance is used up; resting until 00:00 UTC")
        return None
    if not img_b64:
        return None
    dest = CACHE / f"cf_{key}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(img_b64))
    return Visual(dest, "ai_flux_cloudflare", "AI-generated image", "Own (FLUX.1-schnell, Apache 2.0)")


def title_card(text: str, palette: list[str], dest: Path, language: str = "en",
               size: tuple[int, int] = (1080, 1920)) -> Visual:
    """Always-available fallback: gradient card with big text (no outside images)."""
    w, h = size
    top, bottom = palette[0], palette[1] if len(palette) > 1 else "#333333"

    def rgb(c):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

    k = np.linspace(0, 1, h)[:, None, None]
    grad = np.array(rgb(top))[None, None, :] * (1 - k) + np.array(rgb(bottom))[None, None, :] * k
    img = Image.fromarray(np.repeat(grad, w, axis=1).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_file("Hind" if language == "hi" else "Oswald")), 110)
    words, lines, cur = text.split(), [], ""
    for word in words:
        if len(cur + " " + word) > 14 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    lines.append(cur)
    y = h // 2 - len(lines) * 70
    for line in lines[:5]:
        tw = draw.textlength(line, font=font)
        draw.text(((w - tw) / 2, y), line, font=font, fill="white", stroke_width=6, stroke_fill="black")
        y += 140
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, quality=92)
    return Visual(dest, "title_card", "", "Own")


@lru_cache(maxsize=1)
def _embedder():
    from ..memory.store import make_embedder
    from ..config import settings
    return make_embedder(settings()["memory"].get("embedding_model"))


def best_match(candidates: list[Visual], scene_text: str, used: set) -> tuple[Visual | None, float]:
    """Pick the candidate whose title/description best matches the scene."""
    fresh = [c for c in candidates if c.path not in used]
    if not fresh:
        return None, 0.0
    emb = _embedder()
    q = emb.encode([scene_text], is_query=True)[0]
    docs = emb.encode([c.meta.get("text", c.credit) for c in fresh])
    scores = docs @ q
    i = int(np.argmax(scores))
    return fresh[i], float(scores[i])


def ai_image_available() -> bool:
    return bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN")) or         (ROOT / "data" / "gpu_batch").exists()
