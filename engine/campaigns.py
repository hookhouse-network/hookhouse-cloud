"""Campaign reader + scorer.

1. The brain reads a pasted campaign page and pulls out the facts (pay, budget, rules...).
2. Plain code (not AI) decides the India verdict and score, so results are
   consistent and testable.
"""
from __future__ import annotations

import re
import time

from .config import settings

TALKING_CONTENT = ("podcast", "interview", "stream", "talk", "show", "speech", "debate", "commentary")

READER_SYSTEM = "You extract facts from clipping-campaign pages. You never invent facts; unknown = null."

READER_PROMPT = """Read this clipping campaign page and return ONLY a JSON object with these keys:

{{
  "name": string,
  "brand": string|null,
  "cpm_usd": number|null,                 // pay per 1,000 views in USD
  "budget_total_usd": number|null,
  "budget_left_pct": number|null,         // 0-100 if shown or computable
  "min_payout_usd": number|null,          // per clip
  "max_payout_usd": number|null,          // per clip
  "platforms": [string],                  // from: youtube_shorts, instagram_reels, tiktok, facebook_reels, x, snapchat
  "content_type": string,                 // e.g. "podcast clips", "streamer clips", "brand UGC"
  "allowed_sources": [string],            // channels / links we may clip from
  "required_tags": [string],              // hashtags, @mentions, phrases required in caption
  "banned": [string],                     // things that are not allowed
  "length_seconds": {{"min": number|null, "max": number|null}},
  "geo_requirement": {{"us_min_pct": number|null, "tier1_min_pct": number|null, "notes": string|null}},
  "clipper_residency": [string],          // countries clippers must live in / be citizens of; [] if anyone
  "music_allowed": boolean|null,
  "min_views_per_clip": number|null,      // views a clip needs before it is approved / paid (e.g. 1500)
  "required_tool": string|null,           // an editing tool the clips MUST be made with (e.g. "WayinVideo"), else null
  "vague_rejection_terms": boolean,       // true if brand may reject for any reason / unclear rules
  "other_rules": [string]
}}

Campaign link: {url}

Campaign page text:
\"\"\"
{text}
\"\"\"
"""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "campaign").lower()).strip("-")[:40] or "campaign"


def normalize(raw: dict, url: str = "") -> dict:
    """Fill defaults so the rest of the code can rely on every key existing."""
    c = dict(raw)
    c.setdefault("name", "Unnamed campaign")
    c["id"] = c.get("id") or slugify(c["name"])
    c["url"] = c.get("url") or url
    for key in ("platforms", "allowed_sources", "required_tags", "banned", "clipper_residency", "other_rules"):
        c[key] = [str(x) for x in (c.get(key) or [])]
    c["platforms"] = [p.lower().strip() for p in c["platforms"]]
    c["length_seconds"] = c.get("length_seconds") or {"min": None, "max": None}
    c["geo_requirement"] = c.get("geo_requirement") or {}
    c.setdefault("vague_rejection_terms", False)
    c.setdefault("status", "active")
    c.setdefault("joined_at", None)
    c.setdefault("added_at", time.time())
    return c


def india_verdict(c: dict, home: str = "IN") -> tuple[str, str]:
    """Returns (YES | MAYBE | NO, reason)."""
    residency = [r.strip().lower() for r in c.get("clipper_residency", []) if r.strip()]
    home_names = {"in", "india", "indian", "worldwide", "global", "anyone", "any"}
    if residency and not (set(residency) & home_names):
        return "NO", f"Only clippers from: {', '.join(c['clipper_residency'])}"
    platforms = set(c.get("platforms", []))
    if platforms and platforms <= {"tiktok"}:
        return "NO", "TikTok only (TikTok is banned in India)"
    geo = c.get("geo_requirement") or {}
    us, t1 = geo.get("us_min_pct"), geo.get("tier1_min_pct")
    if us or t1:
        need = f"{us}% US" if us else f"{t1}% US/UK/CA/AU"
        return "MAYBE", f"Needs {need} viewers — only accounts that meet this can earn"
    return "YES", "Open to Indian clippers"


def score_campaign(c: dict, cfg: dict | None = None) -> tuple[float, list[str]]:
    """Score 0-10 with reasons. Pure code, no AI."""
    cfg = cfg or settings()["campaigns"]
    verdict, why = india_verdict(c, cfg.get("home_country", "IN"))
    if verdict == "NO":
        return 0.0, [why]
    score, reasons = 0.0, []

    cpm = c.get("cpm_usd")
    if cpm:
        pts = min(cpm / 2.0, 1.0) * 3
        score += pts
        reasons.append(f"Pay ${cpm}/1k views (+{pts:.1f})")
    else:
        reasons.append("Pay rate unknown (+0)")

    left = c.get("budget_left_pct")
    if left is not None:
        pts = max(0.0, min(left, 100)) / 100 * 2
        score += pts
        reasons.append(f"{left:.0f}% budget left (+{pts:.1f})")
    else:
        score += 0.8
        reasons.append("Budget left unknown (+0.8)")

    geo = c.get("geo_requirement") or {}
    need = max(geo.get("us_min_pct") or 0, geo.get("tier1_min_pct") or 0)
    if need == 0:
        score += 2
        reasons.append("No viewer-country rule (+2)")
    elif need <= 40:
        score += 1
        reasons.append(f"Mild country rule {need}% (+1)")
    else:
        reasons.append(f"Strict country rule {need}% (+0)")

    ctype = (c.get("content_type") or "").lower()
    if any(w in ctype for w in TALKING_CONTENT):
        score += 1.5
        reasons.append("Talking content, easy to clip well (+1.5)")
    else:
        score += 0.5
        reasons.append("Non-talking content (+0.5)")

    platforms = set(c.get("platforms", []))
    if platforms & {"youtube_shorts", "instagram_reels"} or not platforms:
        score += 0.5
        reasons.append("YouTube/Instagram allowed (+0.5)")
    else:
        reasons.append("Our platforms not listed (+0)")

    clear = bool(c.get("allowed_sources")) and not c.get("vague_rejection_terms")
    if clear:
        score += 1
        reasons.append("Clear rules + source list (+1)")
    else:
        reasons.append("Vague rules or no source list (+0)")

    if c.get("required_tool"):                      # our own engine makes the clips: a mandatory other tool = no fit
        score = min(score, 2.0)
        reasons.append(f"Clips must be made with {c['required_tool']} (capped at 2)")
    mv = c.get("min_views_per_clip")
    if mv and mv > 10000:
        score -= 1
        reasons.append(f"High minimum of {mv:,} views per clip (-1)")
    if cpm is not None and cpm < cfg.get("min_cpm_usd", 0.5):
        score = min(score, 3.0)
        reasons.append(f"Pay below ${cfg.get('min_cpm_usd', 0.5)} minimum (capped at 3)")
    return round(min(score, 10.0), 1), reasons


def apply_budget_rules(c: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or settings()["campaigns"]
    left = c.get("budget_left_pct")
    if left is not None and left < cfg.get("auto_stop_budget_pct", 30) and c.get("status") == "active":
        c["status"] = "paused_low_budget"
    elif left is not None and left >= cfg.get("auto_stop_budget_pct", 30) and c.get("status") == "paused_low_budget":
        c["status"] = "active"
    return c


def evaluate(c: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or settings()["campaigns"]
    from .campaign_safety import check_campaign
    c["safety"] = check_campaign(c)                 # banned categories, payer, terms: before anything else
    if c["safety"]["verdict"] == "BLOCK":
        c["status"] = "blocked_safety"
    verdict, why = india_verdict(c, cfg.get("home_country", "IN"))
    c["india_verdict"], c["india_reason"] = verdict, why
    c["score"], c["score_reasons"] = score_campaign(c, cfg)
    if verdict == "NO":
        c["status"] = "not_eligible"
    if c.get("status") == "blocked_safety":
        return c
    return apply_budget_rules(c, cfg)


def account_qualifies(c: dict, stats: dict | None) -> tuple[bool, str]:
    """Does a given account's real audience meet the campaign's country rule?"""
    geo = c.get("geo_requirement") or {}
    us_need, t1_need = geo.get("us_min_pct"), geo.get("tier1_min_pct")
    if not us_need and not t1_need:
        return True, "No country rule"
    if not stats:
        return False, "No audience data yet for this account"
    if us_need and (stats.get("us_pct") or 0) < us_need:
        return False, f"US viewers {stats.get('us_pct') or 0:.0f}% < required {us_need}%"
    if t1_need and (stats.get("tier1_pct") or 0) < t1_need:
        return False, f"Tier-1 viewers {stats.get('tier1_pct') or 0:.0f}% < required {t1_need}%"
    return True, "Audience meets the country rule"


def analyze(text: str, url: str, brain) -> dict:
    """Read a campaign page with the brain, then score it with code."""
    raw, result = brain.ask_json("reader", READER_PROMPT.format(url=url or "unknown", text=text[:20000]),
                                 system=READER_SYSTEM, temperature=0.1)
    c = normalize(raw, url)
    c["read_by"] = result.provider
    return evaluate(c)
