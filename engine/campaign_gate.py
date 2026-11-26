"""Campaign gate (owner, 17 Nov 2026): ONE check that every campaign condition is met. A campaign clip comes to the
owner for approval if and only if the gate passes; it runs again at approval and right before posting (a campaign can
end or run out of budget in between).

The briefs' rules are stored as sentences ("Tag @sega_west on TikTok and YouTube", "Add #ad to every post", "Caption
must match the clip"). rules() turns them into:
  - tags:   @mentions / #hashtags our caption must carry (only rules that apply to YouTube or Instagram)
  - starts: a tag the caption must START with ("Start the caption with #ad")
  - ad:     the post is an ad -> #ad in the caption + the on-screen "Ad" label
  - soft:   rules a machine can't tick by text ("Caption must match the clip", "No made-up facts"): an AI checker
            judges them; if it can't answer, the clip waits (never passes by default)
"""
from __future__ import annotations
from engine.core.quiet import noted

import hashlib
import json
import re
import time

TOKEN = re.compile(r"(?<![\w@#])[@#][A-Za-z0-9_.]*[A-Za-z0-9_]")
OUR = {"youtube": "youtube", "instagram": "instagram", "reels": "instagram", "shorts": "youtube", "ig": "instagram",
       "yt": "youtube"}
OTHER = ("tiktok", "x ", "twitter", "snapchat", "facebook", "threads")
AD_TAG = re.compile(r"^#(ad|advertisement|sponsored)$", re.I)
AD_RULE = re.compile(r"#ad\b|ad disclosure|paid partnership|#sponsored|#advertisement", re.I)
STARTS = re.compile(r"(start|begin|open)s?\s+(the\s+|your\s+)?caption\s+with\s+([@#][\w.]+)", re.I)
CTA_ONLY = re.compile(r"\b(rotate|cta|call to action)\b", re.I)      # posting advice, not a pass/fail rule
DEFAULT_LEN = (10, 90)
PLATFORM_MAX = {"youtube": 180, "instagram": 180}


def _plats(rule: str) -> set[str] | None:
    """Which of our platforms a rule is for (None = every platform)."""
    low = f" {rule.lower()} "
    ours = {v for k, v in OUR.items() if re.search(rf"\b{k}\b", low)}
    if ours:
        return ours
    if any(o in low for o in OTHER):
        return set()                                   # a TikTok/X-only rule: not for our posts
    return None


def rules(campaign: dict) -> dict:
    tags: list[str] = []
    soft: list[str] = []
    starts = ""
    ad = bool(campaign.get("disclosure_text"))
    raw = [str(r) for r in (campaign.get("required_tags") or [])] + [str(r) for r in (campaign.get("caption_rules") or [])]
    for r in raw:
        r = r.strip()
        if not r:
            continue
        plats = _plats(r)
        if plats is not None and not plats:
            continue
        toks = [t.rstrip(".") for t in TOKEN.findall(r)]
        m = STARTS.search(r)
        if m:
            starts = m.group(3).rstrip(".")
        if AD_RULE.search(r) or any(AD_TAG.match(t) for t in toks):
            ad = True
            toks = [t for t in toks if not AD_TAG.match(t)]
        if toks:
            tags += toks
        elif not AD_RULE.search(r) and not m and not CTA_ONLY.search(r):
            soft.append(r)                             # an instruction, not a tag
    for r in campaign.get("other_rules") or []:
        r = str(r).strip()
        if r and _plats(r) != set() and re.search(r"caption|title|text|claim|fact|mention|say", r, re.I):
            soft.append(r)
    seen, out = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return {"tags": out, "starts": starts, "ad": ad, "soft": list(dict.fromkeys(soft)),
            "required_text": [str(x) for x in campaign.get("required_text") or []]}


def caption_block(campaign: dict) -> tuple[str, str]:
    """(prefix, suffix) for a campaign clip caption: '#ad' first when the brief says so, the required tags at the end."""
    r = rules(campaign)
    prefix = ""
    if r["starts"]:
        prefix = r["starts"]
    elif r["ad"]:
        prefix = "#ad"
    tail = [t for t in r["tags"] if t.lower() != prefix.lower()]
    lines = [" ".join(tail)] if tail else []
    lines += r["required_text"]
    return prefix, "\n".join(x for x in lines if x)


def has_tag(caption: str, tag: str) -> bool:
    """Exact tag match: '@sega' is NOT inside '@sega_west'."""
    return tag.lower() in {t.lower() for t in TOKEN.findall(caption or "")}


def fix_caption(caption: str, campaign: dict) -> str:
    """Add whatever the rules need that the caption lacks (never removes anything)."""
    prefix, _ = caption_block(campaign)
    if prefix and not caption.lstrip().lower().startswith(prefix.lower()):
        caption = f"{prefix} {caption.lstrip()}"
    r = rules(campaign)
    missing = [t for t in r["tags"] if not has_tag(caption, t) and t.lower() != prefix.lower()]
    missing += [t for t in r["required_text"] if t.lower() not in caption.lower()]
    if missing:
        caption = caption.rstrip() + "\n" + " ".join(missing)
    return caption


STARRED = re.compile(r"\b\w\*{2,}")
# 20 Nov: engine/profanity.py mutes swear words in the audio and stars them in the captions (briefs allow "cut, mute
# or blur"). The judge saw "f***" and held every Dasgas clip as "explicit". The words are gone from what viewers hear;
# the judge still fails real breaches (slurs left in, violence, sexual content).
STARRED_NOTE = ("NOTE: words written with asterisks (like f***) are MUTED in the audio and starred on screen, so "
                "viewers neither hear nor read them. Treat them as removed, not as explicit language. Judge "
                "everything else as usual.\n\n")


def _soft_check(brain, rules_: list[str], caption: str, transcript: str) -> list[str]:
    """AI judge for rules that need reading. Returns problems; raises if no answer (the clip then waits)."""
    if not rules_:
        return []
    prompt = (
        "You check a short video post against a brand campaign's rules before it is sent for approval.\n"
        f"CAPTION:\n{caption[:1500]}\n\nWHAT IS SAID IN THE CLIP:\n{transcript[:2500]}\n\n"
        + (STARRED_NOTE if STARRED.search(f"{caption} {transcript}") else "")
        + "RULES:\n"
        + "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules_))
        + "\n\nFor each rule answer pass, fail, or na (the rule is about something other than this caption/clip, e.g. "
          "how often to post). Fail only on a real breach. Reply JSON only: "
          '[{"rule": 1, "result": "pass|fail|na", "why": "short"}]')
    res = brain.ask("checker", prompt, temperature=0.0).json()
    if not isinstance(res, list):
        raise ValueError("checker gave no list")
    probs = []
    for row in res:
        if str(row.get("result", "")).lower() == "fail":
            k = int(row.get("rule", 0)) - 1
            name = rules_[k] if 0 <= k < len(rules_) else str(row.get("rule"))
            probs.append(f"breaks the rule \"{name[:80]}\" ({str(row.get('why', ''))[:80]})")
    answered = {int(r.get("rule", 0)) for r in res if str(r.get("result", "")).lower() in ("pass", "fail", "na")}
    if answered != set(range(1, len(rules_) + 1)):
        raise ValueError("checker skipped a rule")
    return probs


def check(meta: dict, campaign: dict | None, conn=None, brain=None, transcript: str = "", posted_on=None,
          cache: dict | None = None) -> list[str]:
    """Every campaign condition for one clip. [] = all met. meta = the clip's clips.json entry (or upload meta)."""
    if not meta.get("campaign"):
        return []
    if not campaign:
        return [f"campaign {meta['campaign']} is not in our list any more"]
    p: list[str] = []
    # 1. the campaign itself
    status = str(campaign.get("status") or "")
    if status != "joined":
        p.append(f"campaign is {status or 'not joined'} (only joined campaigns pay)")
    if str(campaign.get("state") or "").lower() in ("ended", "paused", "closed", "completed"):
        p.append(f"campaign is {campaign['state']}")
    left = campaign.get("budget_left_pct")
    try:
        from .config import settings
        stop = float(settings().get("campaigns", {}).get("auto_stop_budget_pct", 30))
    except Exception:  # noqa: BLE001
        stop = 30.0
    if left is not None and float(left) < stop:
        p.append(f"only {float(left):.0f}% of the budget is left (we stop below {stop:.0f}%)")
    try:
        from . import campaign_safety as cs
        v = cs.check_campaign(campaign, conn)
        if v.get("verdict") == "BLOCK":
            p.append("safety check blocks it: " + "; ".join(v.get("block") or [])[:120])
        elif v.get("payer_id") and conn is not None:
            ok, why = cs.can_submit(conn, v["payer_id"])
            if not ok:
                p.append(f"payer on hold: {why}")
    except Exception as e:  # noqa: BLE001 - a check that cannot run is not a pass
        p.append(f"safety check could not run ({str(e)[:60]})")
    # 2. footage and timing
    perm = meta.get("permission") or {}
    if perm.get("basis") != "campaign":
        p.append("footage is not the campaign's own material")
    joined = campaign.get("joined_at")
    made = meta.get("made_at") or meta.get("created_at")
    if not joined:
        p.append("join date unknown")
    elif made and float(made) < float(joined):
        p.append("clip was made before we joined")
    # 3. length and platforms
    ls = campaign.get("length_seconds") or {}
    lo, hi = ls.get("min") or DEFAULT_LEN[0], ls.get("max") or DEFAULT_LEN[1]
    d = float(meta.get("duration_s") or 0)
    if not lo <= d <= hi:
        p.append(f"length {d:.0f}s (campaign allows {lo}-{hi}s)")
    names = [str(x).lower() for x in campaign.get("platforms") or []]
    ours = [pl for pl, n in (("youtube", "youtube_shorts"), ("instagram", "instagram_reels")) if not names or n in names]
    if not ours:
        p.append("the campaign allows none of our platforms (YouTube Shorts / Instagram Reels)")
    for pl in ours:
        if d > PLATFORM_MAX[pl]:
            p.append(f"too long for {pl} ({d:.0f}s)")
    # 4. caption
    caption = str(meta.get("caption") or meta.get("description") or "")
    low = caption.lower()
    r = rules(campaign)
    missing = [t for t in r["tags"] if not has_tag(caption, t)]
    if missing:
        p.append("caption is missing " + ", ".join(missing))
    if r["starts"] and not caption.lstrip().lower().startswith(r["starts"].lower()):
        p.append(f"caption must start with {r['starts']}")
    for t in r["required_text"]:
        if t.lower() not in low:
            p.append(f"caption is missing the required line \"{t[:60]}\"")
    if r["ad"]:
        if not re.search(r"#(ad|advertisement|sponsored)\b", low):
            p.append("caption needs #ad (it is a paid post)")
        if not meta.get("disclosure"):
            p.append("the on-screen Ad label is missing")
    banned = [b for b in campaign.get("banned") or [] if len(str(b)) <= 40
              and str(b).lower() in (low + " " + transcript.lower()) and "footage" not in str(b).lower()]
    if banned:
        p.append("contains banned words: " + ", ".join(banned))
    # 5. look and sound
    if campaign.get("needs_logo") and not meta.get("logo_shown"):
        p.append("the brand logo is not on screen")
    if meta.get("has_added_music"):
        p.append("added music (campaigns only allow the footage's own sound)")
    # 6. no double use
    if posted_on:
        p.append(f"already posted on {', '.join(posted_on)}")
    if conn is not None and meta.get("edit_hash"):
        try:
            row = conn.execute("SELECT campaign_id FROM submissions WHERE edit_hash=? AND campaign_id!=?",
                               (meta["edit_hash"], campaign["id"])).fetchone()
            if row:
                p.append(f"this edit was already sent to campaign {row[0]}")
        except Exception as _swallowed:  # noqa: BLE001 - no submissions table yet
            noted("campaign_gate.py:240", _swallowed)
            pass
    # 7. rules that need reading (AI) - cached per caption so the checker is asked once
    if r["soft"] and not p:
        key = hashlib.sha1(json.dumps([caption, r["soft"]]).encode()).hexdigest()[:16]
        hit = (cache or {}).get(key)
        if hit is None:
            if brain is None:
                p.append("brief rules not checked yet (AI checker unavailable); it tries again")
            else:
                try:
                    hit = _soft_check(brain, r["soft"], caption, transcript)
                    if cache is not None:
                        cache[key] = hit
                except Exception as e:  # noqa: BLE001 - no answer = not passed
                    p.append(f"brief rules not checked yet ({str(e)[:60]}); it tries again")
        if hit:
            p += hit
    return p


def summary(problems: list[str]) -> str:
    return "✅ all campaign conditions met" if not problems else "🛑 " + "; ".join(problems)


def stamp(meta: dict, problems: list[str]) -> dict:
    meta["gate"] = {"passed": not problems, "problems": problems, "at": time.time()}
    meta["rule_check"] = {"passed": not problems, "summary": summary(problems)}
    return meta


def clip_entry(it: dict) -> tuple[dict | None, list, "object"]:
    """The clip's own clips.json entry (has duration, label, logo, transcript, cached AI answers)."""
    from pathlib import Path
    cj = Path(it.get("out_dir") or "") / "clips.json"
    if not cj.exists():
        return None, [], cj
    rows = json.loads(cj.read_text(encoding="utf-8"))
    for c in rows:
        if c.get("file") == it.get("file"):
            return c, rows, cj
    return None, rows, cj


def gate_item(it: dict, brain_fn=None) -> list[str]:
    """The gate for a queued plan item ([] for anything that is not a campaign clip)."""
    meta, rows, cj = clip_entry(it)
    if not meta or not meta.get("campaign"):
        return []
    from . import db
    conn = db.connect()
    campaign = db.get_campaign(conn, meta["campaign"])
    cache = meta.setdefault("gate_cache", {})
    before = json.dumps(cache, sort_keys=True)
    brain = None
    if brain_fn is not None and rules(campaign or {}).get("soft"):
        key = hashlib.sha1(json.dumps([str(meta.get("caption") or ""), rules(campaign)["soft"]]).encode()).hexdigest()[:16]
        if key not in cache:
            try:
                brain = brain_fn()
            except Exception:  # noqa: BLE001 - check() then reports "not checked yet"
                brain = None
    probs = check(meta, campaign, conn=conn, brain=brain, transcript=str(meta.get("transcript") or ""), cache=cache)
    old = (meta.get("gate") or {}).get("problems")
    if json.dumps(cache, sort_keys=True) != before or old != probs:
        stamp(meta, probs)
        cj.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return probs
