"""Search and pick topics and campaigns (owner 20 Nov 2026: "give topic and campaign search and picking module so i
can tell you to research or create the content based on that, similar to the campaign").

    python cli.py pick topics "<idea or niche>" [--channel ID]   ranked angles with live demand evidence
    python cli.py pick topic "<topic>" --channel ID              make it: takes the channel's next unmade slot
    python cli.py pick campaigns ["<search>"]                    ranked campaigns from our campaign database
    python cli.py pick campaign <id> [--account CHANNEL]         add it to config/campaigns_picked.yaml

Topics: the best-fitting channel is chosen from the channel niches (or given); the AI writer proposes angles; every
angle gets demand evidence from YouTube (engine/topic_proof.py) and is checked against the never-topics and
protected-franchise lists before it is shown. A picked topic replaces the topic of the channel's soonest planned,
not-yet-made Short (marked owner_pick, so the planner never overwrites it); if no slot is free it waits in
data/state/topics_picked.json and the next weekly plan uses it first. Everything still passes all gates.
Campaigns: ranked by our own campaign score (pay, budget left, India rules, fit); a pick is written to the owner's
picked list, which the cloud loads into the campaign database. Joining stays the owner's tap."""
from __future__ import annotations

import json
import re
import time

from .config import ROOT

TOPICS_FILE = ROOT / "data" / "state" / "topics_picked.json"
CAMPAIGNS_FILE = ROOT / "config" / "campaigns_picked.yaml"
TIER_ORDER = {"hot": 0, "warm": 1, "unknown": 2, "cold": 3, "none": 4}
WORD = re.compile(r"[a-zऀ-ॿ]{3,}")


def _words(text: str) -> set[str]:
    return set(WORD.findall(str(text or "").lower()))


def best_channels(query: str, k: int = 3) -> list[dict]:
    """Channels whose niche/name/hints share the most words with the query (kids channels last)."""
    from .config import channels
    try:
        from .niche_winners import QUERIES
    except ImportError:
        QUERIES = {}
    q = _words(query)
    scored = []
    for ch in channels():
        if ch.get("active") is False:
            continue
        text = " ".join([ch.get("name", ""), ch.get("niche", ""), " ".join(ch.get("topic_hints") or []),
                         " ".join(QUERIES.get(ch["id"], ())), " ".join(ch.get("hashtags") or [])])
        scored.append((len(q & _words(text)), ch.get("type") == "kids", ch))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for s, _k, c in scored[:k] if s > 0] or [c for _s, _k, c in scored[:1]]


def _safe(text: str) -> list[str]:
    probs = []
    try:
        from .policy import topic_flags
        probs += [f"never-topic: {f}" for f in topic_flags(text, mode="topic")]
    except Exception as e:  # noqa: BLE001
        probs.append(f"never-topic check could not run ({type(e).__name__})")
    try:
        from .ip_guard import hits
        probs += [f"protected name: {h}" for h in hits(text)]
    except Exception as e:  # noqa: BLE001
        probs.append(f"franchise check could not run ({type(e).__name__})")
    return probs


def find_topics(query: str, channel: str | None = None, n: int = 6, brain=None, log=print) -> list[dict]:
    """[{topic, channel, demand, tier, why}] best first."""
    from .config import channel as get_channel
    ch = get_channel(channel) if channel else best_channels(query)[0]
    angles = [query]
    if brain is not None:
        prompt = (f"You plan Shorts for the channel {ch.get('name')} ({ch.get('niche')}) for "
                  f"{'Indian' if ch.get('market') == 'IN' else 'United States'} viewers. The owner wants content about: "
                  f"\"{query}\". Give {n} specific, original Short topics on it with a strong angle each (a surprising "
                  "fact, a question, a turn), factual, no made-up claims. Reply JSON only: "
                  '{"topics": [{"topic": "...", "why": "why people would watch and share it"}]}')
        try:
            data, _r = brain.ask_json("writer", prompt, temperature=0.8)
            got = [t for t in (data.get("topics") or []) if isinstance(t, dict) and t.get("topic")]
            angles = [t["topic"] for t in got[:n]] or angles
            whys = {t["topic"]: t.get("why", "") for t in got}
        except Exception as e:  # noqa: BLE001 - the query itself is still checked
            log(f"topic ideas failed: {type(e).__name__}: {e}")
            whys = {}
    else:
        whys = {}
    from .topic_proof import evidence_text, proof
    out = []
    for a in angles:
        probs = _safe(a)
        if probs:
            log(f"dropped {a!r}: {'; '.join(probs)}")
            continue
        try:
            pr = proof(a, ch, log=log)
        except Exception as e:  # noqa: BLE001
            pr = {"tier": "unknown", "why": type(e).__name__}
        out.append({"topic": a, "channel": ch["id"], "tier": pr.get("tier", "unknown"),
                    "demand": evidence_text(pr), "why": whys.get(a, "")})
    out.sort(key=lambda x: TIER_ORDER.get(x["tier"], 9))
    return out


def suggest(channel: str, n: int = 8, brain=None, log=print, keep=("hot", "warm")) -> list[dict]:
    """Well-researched topics for one channel's menu (owner 20 Nov: "well research topics that are in trend and in
    demand"): the channel's live signals (trend radar, Wikipedia demand bank, what viewers search and ask for) ->
    the writer turns them into angles -> each must show demand NOW on YouTube (topic_proof hot/warm) to be listed."""
    from .config import channel as get_channel
    ch = get_channel(channel)
    signals: list[str] = []
    for name, fn in (("trends", lambda: (__import__("engine.trends", fromlist=["x"]).trend_hints(brain, log=log)
                                         if brain is not None else {}).get(channel, [])),
                     ("demand bank", lambda: __import__("engine.topic_bank", fromlist=["x"]).hints(channel, [])),
                     ("searches", lambda: [t for t, _ in __import__("engine.stats_fetch", fromlist=["x"])
                                           .top_terms(channel, 5)]),
                     ("viewers", lambda: __import__("engine.comments", fromlist=["x"]).ideas(channel, 3))):
        try:
            signals += [str(s) for s in fn() or []]
        except Exception as e:  # noqa: BLE001 - other signals still count
            log(f"suggest {channel}: {name} unavailable ({type(e).__name__})")
    query = f"{ch.get('niche', '')}. Live signals: " + "; ".join(signals[:12]) if signals else ch.get("niche", "")
    got = find_topics(query, channel=channel, n=max(n, 8), brain=brain, log=log)
    good = [t for t in got if t["tier"] in keep]
    return (good or [t for t in got if t["tier"] == "unknown"])[:n]


def pick_topic(topic: str, channel: str, demand: str = "", log=print) -> str:
    """Put the topic on the channel's soonest planned, unmade Short; else queue it for the next weekly plan."""
    probs = _safe(topic)
    if probs:
        return "Not picked: " + "; ".join(probs)
    from . import autopilot
    for start, it in autopilot.items(0, 14):
        if it.get("channel") == channel and it.get("status") == "planned" and it.get("kind") in ("short", "clip") \
                and not it.get("owner_pick") and not it.get("product"):
            autopilot.update_item(start, it["id"], topic=topic, angle=None, role=None, hub=None, owner_pick=True,
                                  demand=demand or None, why="owner picked this topic")
            from .core import ledger
            ledger.event("topic.picked", item=it["id"], channel=channel, data={"topic": topic})
            return f"✅ {topic!r} will be made for {it.get('channel_name') or channel} (slot {it['publish_at'][:16]})."
    q = _load_topics()
    q.setdefault(channel, []).append({"topic": topic, "demand": demand, "at": time.time()})
    from .core.atomic import write_json
    write_json(TOPICS_FILE, q)
    return f"🕒 No free slot this fortnight for {channel}: {topic!r} goes first into the next weekly plan."


def _load_topics() -> dict:
    try:
        return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def queued_topics(channel: str) -> list[dict]:
    """The next weekly plan takes these first (and removes them)."""
    q = _load_topics()
    got = q.pop(channel, [])
    if got:
        from .core.atomic import write_json
        write_json(TOPICS_FILE, q)
    return got


def footage_check(c: dict, mcp=None, live: bool = True) -> tuple[str, str]:
    """BEFORE joining (owner 20 Nov: "make sure you find the footage that the campaign offers ... I don't want any
    issues after joining"). ('ok' | 'unknown' | 'blocked', why). Fail closed: no confirmed permitted footage path =
    never 'ok'.
      ok      - direct footage files from the campaign (Drive/Dropbox/.mp4), or a Kick streamer (Kick's own clip tool)
      unknown - the assets are locked until joining: we can't promise footage
      blocked - only Twitch/YouTube pages (no permitted download) or nothing at all"""
    if c.get("kick"):
        return "ok", f"Kick streamer {c['kick']}: clips through Kick's own clip tool (Kick program/brief)"
    direct = [u for u in c.get("allowed_sources") or [] if re.search(r"drive\.google|dropbox|frame\.io|\.mp4", str(u))]
    if direct:
        return "ok", f"{len(direct)} footage link(s) from the brief"
    ref = c.get("ca_ref") or c.get("ref") or (c.get("id") if str(c.get("source")) == "clippingalpha" else None)
    if live and ref:
        try:
            from .discover import campaign_footage
            f = campaign_footage(str(ref), mcp=mcp)
        except Exception as e:  # noqa: BLE001 - not confirmed = not ok
            return "unknown", f"footage check failed ({type(e).__name__}); not confirmed"
        if f.get("files"):
            return "ok", f"{len(f['files'])} direct footage file(s) on the campaign"
        if f.get("locked_assets"):
            return "unknown", f"{f['locked_assets']} asset(s) visible only after joining: footage not confirmed"
        if f.get("platform_pages"):
            return "blocked", "only Twitch/YouTube pages: no permitted way to download the footage"
    return "blocked", "no footage source found in the brief"


def find_campaigns(query: str = "", n: int = 10, conn=None, live: bool = True, show_all: bool = False) -> list[dict]:
    from . import campaigns, db
    conn = conn or db.connect()
    q = _words(query)
    out = []
    for c in db.list_campaigns(conn):
        if str(c.get("status") or "") in ("ended", "rejected") or \
                str(c.get("state") or "").lower() in ("ended", "paused", "closed", "completed"):
            continue
        text = json.dumps({k: c.get(k) for k in ("name", "brand", "game", "category", "rules", "caption_rules",
                                                 "other_rules", "platforms")}, ensure_ascii=False)
        if q and not (q & _words(text)):
            continue
        try:
            score, why = campaigns.score_campaign(c)
        except Exception as e:  # noqa: BLE001
            score, why = 0.0, [f"score failed: {type(e).__name__}"]
        fv, fwhy = footage_check(c, live=live)
        if fv == "blocked" and not show_all:
            continue
        out.append({"id": c.get("id"), "name": c.get("name"), "status": c.get("status"), "url": c.get("url"),
                    "rate": c.get("rate_per_1k") or c.get("cpm") or c.get("rate"),
                    "budget_left_pct": c.get("budget_left_pct"), "platforms": c.get("platforms"),
                    "footage": fv, "footage_why": fwhy,
                    "score": round(float(score), 2), "why": "; ".join(why[:3]) if isinstance(why, list) else str(why)})
    out.sort(key=lambda x: ({"ok": 0, "unknown": 1, "blocked": 2}[x["footage"]], -x["score"]))
    return out[:n]


def pick_campaign(cid: str, account: str | None = None, conn=None, live: bool = True) -> str:
    from . import db
    import yaml
    c = db.get_campaign(conn or db.connect(), cid)
    if not c:
        return f"No campaign {cid!r} in the database (run: python cli.py campaign discover)."
    fv, fwhy = footage_check(c, live=live)
    if fv != "ok":                                  # owner 20 Nov: no issues after joining
        return f"🛑 Not picked: footage {fv}: {fwhy}. Join only campaigns whose footage we can legally get."
    try:
        cur = yaml.safe_load(CAMPAIGNS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        cur = {}
    if any(str(x.get("id")) == cid for x in cur.get("campaigns") or []):
        return f"{c.get('name')} is already in your picked list."
    entry = {"id": cid, "name": c.get("name"), "url": c.get("url"), "source": c.get("source") or "picked",
             "status": "picked", "platforms": c.get("platforms") or []}
    if account:
        entry["account"] = account
    block = "  - " + yaml.safe_dump(entry, allow_unicode=True, sort_keys=False).replace("\n", "\n    ").rstrip() + "\n"
    with CAMPAIGNS_FILE.open("a", encoding="utf-8") as fh:              # append: the owner's comments stay
        fh.write(f"  # picked {time.strftime('%Y-%m-%d')} with `cli.py pick campaign`; Join stays the owner's tap\n")
        fh.write(block)
    return f"✅ {c.get('name')} added to your picked campaigns. Tap Join on its page: {c.get('url')}"
