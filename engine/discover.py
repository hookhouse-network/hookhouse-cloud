"""Daily campaign discovery: find new paid campaigns we can really fulfil, without breaking platform or channel rules.

Source: ClippingAlpha's public MCP read tools (no sign-in; the interface ClippingAlpha asks tools to use; its robots.txt
welcomes crawlers). It tracks ~900 live campaigns on Content Rewards, Clipster, Vyro, Promote.fun and more. Data used
internally only; reports credit "Data: ClippingAlpha".

Pipeline: search (YouTube/Instagram, new in the last N hours) -> brief (rules, audience, footage, minimum views, cap)
-> our safety check (never-topics, politics, gambling/crypto, payer tier, crypto-only payouts) -> India eligibility
-> can-we-fulfil check (our real capabilities) -> score -> database + daily report. Nothing is joined or posted
automatically: the owner taps join.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from . import campaigns as camp
from . import db
from .config import ROOT

REPORTS = ROOT / "data" / "campaigns"
PLATFORM_MAP = {"youtube": "youtube_shorts", "instagram": "instagram_reels", "tiktok": "tiktok", "x": "x",
                "facebook": "facebook_reels", "snapchat": "snapchat"}
FACE = re.compile(r"\b(face|on[- ]camera|talking to (the )?camera|selfie|show yourself|your voice|unbox|product in hand|"
                  r"try[- ]on|wear(ing)? the|hold(ing)? the product|film yourself|real person|creator on screen)\b", re.I)
FACELESS = re.compile(r"\b(faceless|slideshow|no face|text on screen|carousel|edit[s]? of|b-?roll|clip(ping)?)\b", re.I)
NO_AI = re.compile(r"\b(no ai|ai[- ]generated (content|voice)s? (is|are)? ?not allowed|no ai voice|ai voice(s)? not allowed)\b", re.I)
TOOL = re.compile(r"\b(?:made|created|edited|cut)\s+(?:with|using|in)\s+([A-Z][\w.]+)", re.I)
RESIDENCY = re.compile(r"\b(us|usa|united states|uk|canada|eu|europe)[- ]?(residents?|citizens?|based clippers?)( only)?\b", re.I)
NICHE_ACCOUNT = {"podcast": "hot_take_hq", "business": "hot_take_hq", "finance": "hot_take_hq", "education": "hot_take_hq",
                 "tech": "hot_take_hq", "ai": "hot_take_hq", "self-improvement": "hot_take_hq", "sports": "hot_take_hq",
                 "gaming": "stream_clips", "streamer": "stream_clips", "streaming": "stream_clips", "kick": "stream_clips",
                 "twitch": "stream_clips"}


def _texts(brief: dict) -> str:
    w = brief.get("wants") or {}
    parts = [json.dumps(w, ensure_ascii=False)]
    parts += [str(x.get("text", "")) for x in brief.get("checklist") or []]
    return " ".join(parts)


def to_campaign(item: dict, brief: dict) -> dict:
    """Our campaign schema (engine/campaigns.py) from a ClippingAlpha search item + brief."""
    w = brief.get("wants") or {}
    j = brief.get("join") or {}
    checklist = brief.get("checklist") or []
    text = _texts(brief)
    countries = [str(c) for c in w.get("audienceCountries") or []]
    geo = {"us_min_pct": None, "tier1_min_pct": None, "notes": None}
    if countries and not any(c.lower() in ("in", "india", "global", "worldwide", "any") for c in countries):
        geo["tier1_min_pct"] = 50                         # unknown exact share: treat as a strict Tier-1 rule
        geo["notes"] = "Audience countries: " + ", ".join(countries)
    m = re.search(r"(\d{2,3})\s*%\s*(?:of (?:the )?(?:viewers|audience) )?(?:from )?(?:the )?(us|usa|united states|tier ?1)", text, re.I)
    if m:
        geo["tier1_min_pct" if "tier" in m.group(2).lower() else "us_min_pct"] = int(m.group(1))
    residency = sorted({r.group(1).upper() for r in RESIDENCY.finditer(text)})
    tool = TOOL.search(text)
    total = item.get("budgetTotalUsd") or 0
    left = item.get("budgetLeftUsd")
    c = {
        "name": item.get("title") or brief.get("campaign", {}).get("title") or "Campaign",
        "brand": item.get("brand"),
        "url": brief.get("briefUrl") or item.get("pageUrl"),
        "ca_page": item.get("pageUrl"),
        "ca_ref": f"{item.get('brandSlug')}/{item.get('seriesSlug')}",
        "drain_at": item.get("drainP50"),            # ClippingAlpha's estimate of when the budget runs out
        "board": item.get("board"),
        "cpm_usd": item.get("ratePer1kUsd"),
        "net_cpm_usd": item.get("netPer1kUsd"),
        "budget_total_usd": total or None,
        "budget_left_pct": round(100 * left / total, 1) if (total and left is not None) else None,
        "min_payout_usd": j.get("minPayoutUsd"),
        "max_payout_usd": j.get("maxPayoutUsd"),
        "min_views_per_clip": j.get("minViews"),
        "platforms": [PLATFORM_MAP.get(p, p) for p in item.get("platforms") or []],
        "content_type": f"{item.get('campaignType') or ''} {item.get('niche') or ''}".strip(),
        "campaign_type": item.get("campaignType"),
        "niche": item.get("niche"),
        "allowed_sources": [w.get("footage")] if w.get("footage") else [],
        "required_tags": [x.get("text", "") for x in checklist if x.get("kind") in ("caption", "disclosure")],
        "banned": [str(a) for a in w.get("avoid") or []],
        "length_seconds": {"min": None, "max": None},
        "geo_requirement": geo,
        "clipper_residency": residency,
        "music_allowed": None,
        "vague_rejection_terms": bool(brief.get("rulesHidden")),
        "required_tool": tool.group(1) if tool else None,
        "other_rules": [x.get("text", "") for x in checklist if x.get("kind") not in ("caption", "disclosure")],
        "alpha_score": item.get("alphaScore"),
        "open_join": item.get("openJoin"),
        "members_only": item.get("membersOnly"),
        "regulated": bool(item.get("ageRestricted")),
        "election": bool(item.get("election")),
        "can_cut": item.get("canCut"),
        "source": "clippingalpha",
        "status": "discovered",
        "discovered_at": time.time(),
    }
    return camp.normalize(c, c["url"] or "")


def fit_check(c: dict, brief: dict) -> tuple[str, list[str], str | None]:
    """Can WE fulfil it, within platform policy and our rules? -> (OK | REVIEW | NO, reasons, suggested account)."""
    text = _texts(brief)
    why, verdict = [], "OK"

    def no(reason):
        nonlocal verdict
        verdict = "NO"
        why.append(reason)

    def review(reason):
        nonlocal verdict
        if verdict != "NO":
            verdict = "REVIEW"
        why.append(reason)

    langs = [str(x).lower() for x in ((brief.get("wants") or {}).get("languages") or [])]
    name_l0 = (c.get("name") or "").lower()
    other = [x for x in langs if x not in ("english", "en", "hindi", "hi", "any")]
    if (langs and not any(x in ("english", "en", "hindi", "hi", "any") for x in langs)) or             re.search(r"\b(spanish|portuguese|french|german|arabic|japanese|korean|italian|turkish)\b", name_l0):
        no("Posts must be in " + (", ".join(other) or "another language") + " (we post in English/Hindi)")
    plats = set(c.get("platforms") or [])
    if not plats & {"youtube_shorts", "instagram_reels"}:
        no("Pays only on apps we don't use (TikTok is banned in India)")
    if c.get("election"):
        no("Election/political campaign (never-topic)")
    if c.get("regulated"):
        no("Regulated category (gambling, crypto trading, health products)")
    if c.get("members_only"):
        review("Members-only campaign: needs an invite")
    ctype = (c.get("campaign_type") or "").lower()
    if ctype == "ugc":
        if FACE.search(text):
            no("UGC that needs a real face, voice or physical product (we are faceless)")
        elif not FACELESS.search(text):
            review("UGC brief doesn't say faceless is allowed: check before joining")
    elif ctype == "logo":
        review("Logo campaign: only on a campaign account, never on monetised story channels; tick 'paid promotion'")
    elif ctype == "music":
        review("Music campaign: the rights holder must own the sound; Instagram only, never on the kids channel")
    if NO_AI.search(text) and ctype != "clipping":
        no("Brief bans AI voices/content")
    if c.get("required_tool"):
        no(f"Clips must be made with {c['required_tool']} (we use our own engine)")
    if c.get("clipper_residency"):
        no("Clippers must live in: " + ", ".join(c["clipper_residency"]))
    geo = c.get("geo_requirement") or {}
    if geo.get("tier1_min_pct") or geo.get("us_min_pct"):
        review(f"Needs a US/Tier-1 audience ({geo.get('notes') or 'share required'}): join only with an account that has it")
    mv = c.get("min_views_per_clip")
    if mv and mv > 10000:
        review(f"High minimum of {mv:,} views per clip: hard for new accounts")
    if ctype == "clipping" and not c.get("allowed_sources") and c.get("can_cut") is False:
        review("No public source footage listed: check the brief for the footage link")
    name_l = (c.get("name") or "").lower()
    if re.search(r"\b(movie|film|trailer|tv|series|season|anime|album|single|music video|mv)\b", name_l) or             (c.get("niche") or "").lower() in ("movies", "film", "tv", "music", "entertainment", "anime"):
        why.append("Film/TV/music IP: licensed by the brief, so post ONLY on a campaign account (Hot Take HQ or a new "
                   "entertainment clips account), never on Ending Decoded or Picture Abhi Baaki Hai; keep the brief as proof")
    acct = None
    niche = (c.get("niche") or "").lower()
    for k, v in NICHE_ACCOUNT.items():
        if k in niche or k in (c.get("name") or "").lower():
            acct = v
            break
    if ctype == "clipping" and not acct:
        acct = "hot_take_hq"
    return verdict, why, acct


def discover(hours: int = 48, per_type: int = 25, max_briefs: int = 30, log=print, refresh: bool = False) -> Path:   # server max 25
    from .ca_mcp import MCP
    REPORTS.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    known = set() if refresh else {c.get("ca_ref") for c in db.list_campaigns(conn)}
    m = MCP()
    found: dict[str, dict] = {}
    searches = [{"type": t} for t in ("clipping", "ugc", "music", "logo")]
    searches += [{"type": "clipping", "niche": n} for n in ("streams", "gaming")]       # streamer / gameplay clipping
    searches += [{"query": q} for q in ("GTA", "Grand Theft Auto", "Rockstar")]           # hot topic: GTA 6
    for args in searches:
        typ = args.get("niche") or args.get("query") or args.get("type")
        try:
            res = m.tool("search_campaigns", platforms=["youtube", "instagram"], limit=min(per_type, 25),
                         new_within_hours=hours, **args)
        except Exception as e:  # noqa: BLE001
            log(f"  search {typ}: {e}")
            continue
        for it in (res.get("campaigns") if isinstance(res, dict) else []) or []:
            if it.get("state") == "live":
                found[str(it.get("campaignId"))] = it
    log(f"Discovery: {len(found)} new live campaigns on YouTube/Instagram in the last {hours} h")
    # cheap structural filters first, then read briefs for the best-scored remaining ones
    pre = []
    for it in found.values():
        ref = f"{it.get('brandSlug')}/{it.get('seriesSlug')}"
        if ref in known or it.get("election") or it.get("ageRestricted"):
            continue
        pre.append(it)
    pre.sort(key=lambda x: (x.get("alphaScore") or 0, x.get("ratePer1kUsd") or 0), reverse=True)
    from . import hot_topics as hot
    tops = hot.topics()
    pre.sort(key=lambda x: hot.match({"name": x.get("title"), "brand": x.get("brand"), "niche": x.get("niche"),
                                      "campaign_type": x.get("campaignType")}, tops)[1], reverse=True)  # stable
    rows = []
    for it in pre[:max_briefs]:
        ref = f"{it.get('brandSlug')}/{it.get('seriesSlug')}"
        try:
            brief = m.tool("get_brief", campaign=ref)
            brief = brief if isinstance(brief, dict) else {}
        except Exception as e:  # noqa: BLE001
            log(f"  brief {ref}: {e}")
            continue
        c = to_campaign(it, brief)
        c = camp.evaluate(c)                         # safety (never-topics, payer, terms) + India verdict + score
        verdict, why, acct = fit_check(c, brief)
        if c.get("status") in ("blocked_safety", "not_eligible"):
            verdict = "NO"
            why = (c.get("safety", {}).get("block") or [c.get("india_reason", "")]) + why
        elif (c.get("safety") or {}).get("verdict") == "REVIEW" and verdict == "OK":
            verdict = "REVIEW"
            why += c["safety"].get("review") or []
        c["fit"], c["fit_reasons"], c["account"] = verdict, why, acct
        c["hot"], c["hot_boost"] = hot.match(c, tops)                 # GTA 6 / trending: top of the phone list
        c["status"] = {"OK": "eligible", "REVIEW": "review", "NO": "rejected"}[verdict] \
            if c.get("status") == "discovered" or verdict == "NO" else c["status"]
        db.save_campaign(conn, c)
        rows.append(c)
        log(f"  {verdict:6} {c.get('score', 0):>4} ${c.get('cpm_usd')}/1K {c['name'][:60]}")
    return _report(rows, hours)


def refresh_states(rows: list[dict], mcp=None, conn=None, limit: int = 25) -> list[dict]:
    """Re-check each campaign's live state just before it is offered (17 Nov: two of the owner's picks had been
    paused/ended for a day). Paused or ended ones get status "ended" and are dropped; the rest come back."""
    if not rows or not any(c.get("ca_ref") for c in rows[:limit]):
        return rows
    if mcp is None:
        from .ca_mcp import MCP
        mcp = MCP()
    conn = conn or db.connect()
    keep = []
    for c in rows[:limit]:
        state = None
        if c.get("ca_ref"):
            try:
                b = mcp.tool("get_brief", campaign=c["ca_ref"])
                state = ((b or {}).get("campaign") or {}).get("state") if isinstance(b, dict) else None
            except Exception:  # noqa: BLE001 - unknown state: keep it (the PC page check still catches a pause)
                state = None
        if state and state != "live":
            c["status"], c["ended_reason"] = "ended", f"board says {state}"
            db.save_campaign(conn, c)
            continue
        keep.append(c)
    return keep + rows[limit:]


DIRECT_FILE = re.compile(r"(drive\.google\.com/(file/d/|open\?id=|uc\?)|dropbox\.com/\S+\.(mp4|mov|mkv|webm)|"
                         r"\.(mp4|mov|mkv|webm)(\?|$))", re.I)


def _urls(obj) -> list[str]:
    if isinstance(obj, dict):
        return [u for v in obj.values() for u in _urls(v)]
    if isinstance(obj, list):
        return [u for v in obj for u in _urls(v)]
    return [obj] if isinstance(obj, str) and obj.startswith("http") else []


def campaign_footage(ref: str, mcp=None) -> dict:
    """The campaign's own source files (ClippingAlpha get_assets). Only direct file links (Google Drive file, Dropbox,
    .mp4) can be used; video-platform pages (Twitch/YouTube/Kick) are never downloaded."""
    from .clips import PLATFORM_LINKS
    if mcp is None:
        from .ca_mcp import MCP
        mcp = MCP()
    a = mcp.tool("get_assets", campaign=ref)
    a = a if isinstance(a, dict) else {}
    urls = list(dict.fromkeys(_urls({"v": a.get("videos"), "b": a.get("brandAssets"), "l": a.get("library")})))
    files = [u for u in urls if DIRECT_FILE.search(u) and not PLATFORM_LINKS.search(u)]
    pages = [u for u in urls if PLATFORM_LINKS.search(u) and "?t=" not in u]
    return {"files": files, "platform_pages": len(pages), "locked_assets": a.get("brandAssetCount") or 0}


def _report(rows: list[dict], hours: int) -> Path:
    day = datetime.now().strftime("%Y-%m-%d")
    order = {"OK": 0, "REVIEW": 1, "NO": 2}
    rows = sorted(rows, key=lambda c: (order.get(c.get("fit"), 3), -(c.get("score") or 0)))
    lines = [f"# New campaigns we can fulfil ({day})", "",
             f"Searched campaigns new in the last {hours} h that pay on YouTube or Instagram. Data: ClippingAlpha "
             "(clippingalpha.com). Nothing is joined automatically: join on the board after reading the brief.", "",
             "| Fit | Score | Campaign | $/1K (net) | Budget left | Min views | Cap/clip | Account | Why |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c in rows:
        lines.append(f"| {c.get('fit')} | {c.get('score')} | [{c['name'][:55]}]({c.get('url')}) | "
                     f"{c.get('cpm_usd')} ({c.get('net_cpm_usd')}) | {c.get('budget_left_pct')}% | "
                     f"{c.get('min_views_per_clip') or '-'} | {c.get('max_payout_usd') or '-'} | {c.get('account') or '-'} | "
                     f"{'; '.join(x for x in c.get('fit_reasons') or [] if x)[:220] or 'Fits our rules and tools'} |")
    ok = sum(1 for c in rows if c.get("fit") == "OK")
    rv = sum(1 for c in rows if c.get("fit") == "REVIEW")
    lines += ["", f"**{ok} ready to join, {rv} to check, {len(rows) - ok - rv} rejected.**",
              "Before joining: read the brief, copy the required tags word for word, add the disclosure, and post "
              "only on the suggested account. Submit within 30 minutes of posting."]
    path = REPORTS / f"daily_{day}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
