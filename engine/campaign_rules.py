"""Brand rules from a joined campaign's page/brief (17 Nov 2026: SEGA "Show the brand logo on screen", "Caption must
include #Ad", "Caption must mention @SEGA_West on YouTube"). Clips that break these get rejected, so they are read once
when the campaign is joined and applied to every clip:

- required_tags: the hashtags / @mentions the caption must carry (YouTube + Instagram, our two clip platforms)
- disclosure_text: "Ad" pill on screen when the brief demands an ad disclosure
- needs_logo + logo_urls: the brand logo goes on screen (top right) for the whole clip
"""
from __future__ import annotations

import re
from pathlib import Path

OUR_PLATFORMS = ("youtube", "instagram")
AD = re.compile(r"#(ad|advertisement|sponsored)\b", re.I)
LOGO = re.compile(r"(show|include)[^.\n]{0,30}\blogo\b|\blogo or watermark\b", re.I)
LOGO_URL = re.compile(r"https://[^\s\"']*crusercontent\.com/[^\s\"']*/references/assets/[^\s\"']+\.(png|webp|jpe?g)", re.I)


def parse(text: str, links: list[str] | None = None) -> dict:
    tags: list[str] = []
    for line in re.split(r"[\n|]+", text or ""):
        low = line.lower()
        if not re.search(r"caption|must|include|mention|tag", low):
            continue
        plats = [p for p in ("tiktok", "instagram", "youtube", "x ") if p in low]
        if plats and not any(p in plats for p in OUR_PLATFORMS):
            continue                                   # a TikTok/X-only rule: not for our posts
        if AD.search(line) and re.search(r"one of", low):
            tags.append("#Ad")                         # "one of #Ad, #Advertisement or #Sponsored": the short one
        else:
            tags += re.findall(r"#\w+", line)
        tags += re.findall(r"@[\w.]+", line)
    tags = list(dict.fromkeys(t.rstrip(".") for t in tags))
    out = {"required_tags": tags}
    if any(AD.fullmatch(t) for t in tags) or re.search(r"ad disclosure|paid partnership", text or "", re.I):
        out["disclosure_text"] = "Ad"
        if "#Ad" not in tags and not any(AD.fullmatch(t) for t in tags):
            out["required_tags"].append("#Ad")
    if LOGO.search(text or ""):
        out["needs_logo"] = True
        out["logo_urls"] = list(dict.fromkeys(m.group(0) for u in (links or []) for m in [LOGO_URL.search(u)] if m))[:3]
    return out


def logo_file(campaign: dict, folder: Path) -> Path | None:
    """The brand logo as a PNG with transparency (downloaded once per clip batch)."""
    if not campaign.get("needs_logo"):
        return None
    import io

    import requests
    from PIL import Image
    for url in campaign.get("logo_urls") or []:
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGBA")
        except Exception:  # noqa: BLE001 - try the next one
            continue
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / "_brand_logo.png"
        im.save(dest)
        return dest
    return None
