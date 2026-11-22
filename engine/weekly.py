"""Week-ahead batch: plan, make, then the owner approves every video before anything is scheduled.

1. plan_week()  7 days of posting slots for every channel, each with a fresh, non-repeating topic.
2. make_week()  makes every planned video. It can be stopped and started again, because
                finished items are skipped.
3. serve()      a private approval page (local web server, random access key in the link).
                The owner approves, rejects or asks for a change on each video. Nothing is
                uploaded from here: approved items wait for the uploader.

Plans live in data/weeks/<monday>/plan.json; videos stay in output/<channel>/...
"""
from __future__ import annotations

import html
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
import traceback
import urllib.parse
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from .policy import never_rules_text, topic_flags
from .config import ROOT, channels, settings

WEEKS_DIR = ROOT / "data" / "weeks"
OUTPUT_DIR = ROOT / "output"
CLIP_SOURCES = ROOT / "data" / "clip_sources.txt"   # one source per line: "<link or file> [campaign_id]"
BUILDABLE = {"story", "brainrot", "clips", "kids"}           # channel types the system can make today
TO_MAKE = {"planned", "failed", "redo", "needs_source"}
DECISIONS = {"approve": "approved", "reject": "rejected", "redo": "redo", "undo": "made"}
_LOCK = threading.Lock()


class NeedsSource(RuntimeError):
    """A clip slot has no source video yet (add one to data/clip_sources.txt)."""


# ---------- dates and slots ----------

def _zone() -> ZoneInfo:
    return ZoneInfo(settings()["timezone"])


def next_monday(today: date | None = None) -> date:
    today = today or datetime.now(_zone()).date()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _default_times(ch: dict) -> list[tuple[int, int]]:
    raw = ch.get("posting_slots") or settings()["posting_slots"][ch["market"]]
    return sorted(tuple(int(x) for x in s.split(":")) for s in raw)


def _times(ch: dict) -> list[tuple[int, int]]:
    """The channel's slots: learned from its own numbers when the evidence is strong (engine/timing.py), else the
    research defaults. Learned slots fill the first places; unused defaults stay behind them for long videos."""
    base = _default_times(ch)
    try:
        from .timing import slots_for_channel
        learned, _ = slots_for_channel(ch["id"])
    except Exception:  # noqa: BLE001
        learned = None
    if not learned:
        return base
    first = sorted(tuple(int(x) for x in s.split(":")) for s in learned)
    return first + [t for t in base if t not in first]


def _explore_time(ch: dict) -> tuple[int, int] | None:
    try:
        from .timing import slots_for_channel
        _, ex = slots_for_channel(ch["id"])
    except Exception:  # noqa: BLE001
        return None
    return tuple(int(x) for x in ex.split(":")) if ex else None


def _long_shift(channel_id: str) -> int:
    """Position of the channel among channels that make long videos (a long video takes this PC 1.5-4.5 hours;
    all of them on one day would need ~44 hours)."""
    ids = [c["id"] for c in channels() if int((c.get("schedule") or {}).get("long_per_week", 0)) > 0]
    return ids.index(channel_id) if channel_id in ids else 0


def respread_long(start: str, log=print) -> int:
    """Move a plan's not-yet-made long videos to the channel's own long day (same time of day)."""
    from .config import channel as get_channel
    moved = 0
    with _LOCK:
        plan = load_plan(start)
        monday = date.fromisoformat(plan["start"])
        for it in plan["items"]:
            if it.get("kind") != "long" or it.get("status") not in ("planned", "not_built"):
                continue
            new = [w for w, k in slots_for(get_channel(it["channel"]), monday) if k == "long"]
            if new and new[0].isoformat() != it["publish_at"]:
                it["publish_at"] = new[0].isoformat()
                moved += 1
        if moved:
            plan["items"].sort(key=lambda x: (x["publish_at"], x.get("number") or 0))
            save_plan(plan)
    log(f"{start}: {moved} long videos moved to their own day")
    return moved


def spread_times(times: list[tuple[int, int]], n: int, gap_min: int = 60) -> list[tuple[int, int]]:
    """The peak times first, then extra half-hour times as far as possible from every chosen one (at least gap_min
    apart, so one account never posts in bursts), until there are n (20 Nov: volume follows the upload limits)."""
    out = list(times)
    mins = lambda t: t[0] * 60 + t[1]
    cands = [(h, m) for h in range(24) for m in (0, 30)]
    while len(out) < n:
        def dist(c):
            return min((min(abs(mins(c) - mins(t)), 1440 - abs(mins(c) - mins(t))) for t in out), default=1440)
        best = max((c for c in cands if c not in out), key=dist, default=None)
        if best is None or dist(best) < gap_min:
            break
        out.append(best)
    return out


def slots_for(ch: dict, start: date, days: int = 7) -> list[tuple[datetime, str]]:
    """Posting slots for one channel in the week starting `start` (India time)."""
    zone, sched, times = _zone(), ch.get("schedule", {}), _times(ch)
    from .allocator import shorts_per_day              # 20 Nov: analytics-driven volume (engine/allocator.py)
    spd = shorts_per_day(ch)
    if spd > len(times) - (1 if int(sched.get("long_per_week", 0)) else 0):
        times = spread_times(times, spd + 1)          # more Shorts than peak times: extra slots spread over the day
    short_kind = "clip" if ch.get("type") == "clips" else "short"
    out = []
    explore = _explore_time(ch)
    from .timing import EXPLORE_DAYS
    for d in range(days):
        day = start + timedelta(days=d)
        todays = list(times[:spd])
        if explore and todays and day.weekday() in EXPLORE_DAYS and explore not in times:
            todays[-1] = explore                          # a measured experiment, twice a week (engine/timing.py)
        for h, m in todays:
            out.append((datetime(day.year, day.month, day.day, h, m, tzinfo=zone), short_kind))
    n_week = int(sched.get("shorts_per_week", 0))             # a few Shorts a week (e.g. the kids channel)
    for i in range(n_week):
        day = start + timedelta(days=min(days - 1, round((i + 0.5) * days / n_week)))
        h, m = times[0]
        out.append((datetime(day.year, day.month, day.day, h, m, tzinfo=zone), short_kind))
    n_long = int(sched.get("long_per_week", 0))
    shift = _long_shift(ch["id"]) if days >= 7 else 0       # each channel its own day: one PC renders them all
    long_days = ch.get("long_days") or ([(round(i * days / n_long) + 1 + shift) % 7 for i in range(n_long)]
                                        if n_long else [])
    if ch.get("long_slot"):
        lh, lm = tuple(int(x) for x in ch["long_slot"].split(":"))
    else:   # never the same minute as the channel's Short: the first daily slot its Shorts don't use
        free = times[max(1, spd):]
        lh, lm = free[0] if free else times[-1]
    for d in long_days:
        day = start + timedelta(days=min(int(d), days - 1))
        out.append((datetime(day.year, day.month, day.day, lh, lm, tzinfo=zone), "long"))
    return sorted(out)


# ---------- plan storage ----------

def week_dir(start: date | str) -> Path:
    return WEEKS_DIR / (start if isinstance(start, str) else start.isoformat())


def load_plan(start: date | str) -> dict:
    path = week_dir(start) / "plan.json"
    if not path.exists():
        raise FileNotFoundError(f"No plan for the week of {start}. Run: python cli.py week plan")
    return json.loads(path.read_text(encoding="utf-8"))


def _audit_statuses(path: Path, plan: dict) -> None:
    """Lifecycle check (engine/core/lifecycle.py): compares the saved plan with the new one. In enforce mode an
    illegal change raises before anything is written; in observe mode it is logged and sent to the heal queue."""
    from .core import ledger, lifecycle
    try:
        before = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError) as e:                     # unreadable old plan: say so, never hide it
        ledger.event("plan.unreadable", data={"path": str(path), "error": f"{type(e).__name__}: {e}"})
        before = None

    def report(area, error, channel=""):
        try:
            from . import heal
            heal.report(area, error, channel=channel)
        except Exception as e:  # noqa: BLE001 - reporting must not stop the save
            print(f"lifecycle: heal report failed: {e}")
    lifecycle.audit(before, plan, log_event=ledger.event, report=report)


def save_plan(plan: dict) -> Path:
    folder = week_dir(plan["start"])
    folder.mkdir(parents=True, exist_ok=True)
    _audit_statuses(folder / "plan.json", plan)             # 20 Nov: every status change checked + logged
    tmp = folder / "plan.json.tmp"
    tmp.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, folder / "plan.json")
    return folder / "plan.json"


def latest_week() -> str | None:
    weeks = sorted(p.name for p in WEEKS_DIR.glob("*") if (p / "plan.json").exists()) if WEEKS_DIR.exists() else []
    return weeks[-1] if weeks else None


# ---------- topics ----------

TOPIC_PROMPT = """You plan next week's videos for the channel "{name}".
Niche: {niche}
Audience: {audience}. Videos are in {language}. Today is {today}.

Suggest {n} different video topics. Rules (owner 19 Nov: our videos look outdated and get swiped; they must be
trending, funny, emotional, nostalgic, interesting):
- SCROLL-STOP FIRST: a stranger scrolling the feed must stop for the title alone. Score each topic 1-10 for that
  ("scroll_stop"); only topics you honestly score 8+ count.
- CURRENT: at least 2 of every 3 topics tie into something people talk about THIS week (the live trends below, a match,
  a film or show, a festival, the season, a viral moment, a new gadget or price). The rest must still connect to the
  viewer's life today; never a dusty history lesson for its own sake.
- FEELING: each topic delivers ONE strong feeling: funny, emotional, nostalgic, shocking, satisfying, relatable or awe.
  Mix the feelings across the week.
- Each topic is specific (a named person, event, place, object or question) and true, checkable in solid sources.
- SEARCHABLE: the topic contains the words people actually type this week (names, the trend term), so search and
  suggested videos can find it.
- Each topic has a curiosity hook the video can fully pay off. No misleading clickbait.
- Vary the story type (mystery, record, mistake, origin story, twist, myth-busting, "what happened next", "then vs now")
  so the videos never feel like a template.
- Never repeat or closely resemble these past topics: {avoid}
- Never pick a topic that another of our channels already has this week: {taken}
{never}
{style}{memory}{hints}
{cluster}Return JSON only: {{"topics": [{{"topic": "...", "angle": "one-line hook", "why": "why it gets views now", "feeling": "funny|emotional|nostalgic|shocking|satisfying|relatable|awe", "now_hook": "the current trend, event or everyday link (or \"evergreen\")", "scroll_stop": 8}}],
"hub": 0, "spokes": [{{"topic": "...", "angle": "...", "why": "..."}}]}}"""
CLUSTER_RULE = """- TOPIC CLUSTER (hub and spokes, the way top search strategies plan content): set "hub" to the index of the
  topic that makes the best 9-12 minute long video (rich, several twists), and write 2 "spokes": extra Short topics, each
  answering ONE surprising sub-question of that hub (true and checkable on its own). They lead Shorts viewers to it.
"""


def _stale(it: dict, days: int = 3) -> bool:
    """A planned slot more than `days` in the past: its video will not be made any more (cloud.runner.OVERDUE_D)."""
    try:
        when = datetime.fromisoformat(it["publish_at"])
    except (KeyError, ValueError):
        return False
    return when < datetime.now(when.tzinfo) - timedelta(days=days)


def past_topics(channel_id: str, limit: int = 80) -> list[str]:
    """Titles/topics this channel already made or planned, newest first."""
    seen: list[tuple[float, str]] = []
    for script in (OUTPUT_DIR / channel_id).glob("*/script.json"):
        try:
            s = json.loads(script.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in ("title", "topic"):
            if s.get(key):
                seen.append((script.stat().st_mtime, str(s[key])[:120]))
    for plan_file in WEEKS_DIR.glob("*/plan.json") if WEEKS_DIR.exists() else []:
        try:
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for it in plan.get("items", []):
            if it.get("channel") != channel_id or not it.get("topic") or it.get("status") == "rejected":
                continue
            # 18 Nov (owner: "you are giving the topics but you haven't generated the content ... it got waste"):
            # a topic counts as used only if its video was made, or is still coming. Never-made topics from past
            # slots go back to the pool and can be planned again.
            if it.get("status") in TO_MAKE and _stale(it):
                continue
            seen.append((plan_file.stat().st_mtime, it["topic"][:120]))
    out, keys = [], set()
    for _, t in sorted(seen, reverse=True):
        k = re.sub(r"\W+", " ", t.lower()).strip()
        if k not in keys:
            keys.add(k)
            out.append(t)
    return out[:limit]


def _weak(t: dict, floor: int = 7) -> bool:
    """A topic the writer scored under `floor` for stopping the scroll (missing score = kept)."""
    try:
        return t.get("scroll_stop") is not None and float(t["scroll_stop"]) < floor
    except (TypeError, ValueError):
        return False


def franchise_names(t: dict) -> list[str]:
    """Protected film/game/comic names in a topic (engine/ip_guard.py, the same list the content gate uses). 20 Nov
    gate report: Ending Decoded (Avengers, Doctor Doom, MCU) and Money Cheat Codes (GTA 6) videos were made, then held
    by the content gate. Shift-left: such topics are never picked."""
    from .ip_guard import hits
    return hits(f"{t.get('topic', '')} {t.get('angle', '')}")


def pick_topics(brain, ch: dict, n: int, memory=None, hints: list[str] | None = None,
                taken: list[str] | None = None, log=print, cluster_out: dict | None = None) -> list[dict]:
    """cluster_out (a dict) asks for a hub topic (index, for the long video) and 2 spoke Shorts, filled in place."""
    if n <= 0:
        return []
    avoid = past_topics(ch["id"])
    mem = memory.context_block(ch["niche"], ch["id"]) if memory else ""
    from .topic_bank import hints as demand_hints        # real search demand (Wikipedia views) for this niche
    hints = list(hints or []) + list(ch.get("topic_hints", [])) + demand_hints(ch["id"], avoid)
    try:                                                 # what our own viewers asked for in the comments
        from .comments import ideas as viewer_ideas
        hints += viewer_ideas(ch["id"], 3)
    except Exception:  # noqa: BLE001
        pass
    try:                                                 # lessons from the end-of-day reviews (18 Nov)
        from .daily_review import planner_hints
        hints += planner_hints(ch["id"])
    except Exception:  # noqa: BLE001
        pass
    try:                                                 # 19 Nov: this channel's own numbers -> what must change
        from .content_tuning import topic_hints
        hints += topic_hints(ch["id"])
    except Exception:  # noqa: BLE001
        pass
    prompt = TOPIC_PROMPT.format(
        name=ch["name"], niche=ch["niche"], n=n,
        audience="United States viewers" if ch["market"] == "US" else "Indian viewers",
        language="Hindi" if ch.get("language") == "hi" else "English",
        today=datetime.now(_zone()).strftime("%d %B %Y"),
        avoid="; ".join(avoid) if avoid else "(none yet)",
        taken="; ".join(taken) if taken else "(none yet)",
        style=f"Format notes for this channel: {ch['topic_style']}\n" if ch.get("topic_style") else "",
        memory=f"What worked before:\n{mem}\n" if mem else "",
        never=never_rules_text(), cluster=CLUSTER_RULE if cluster_out is not None else "",
        hints=("Ideas to consider (live trends, calendar, owner notes; use only what truly fits):\n- "
               + "\n- ".join(hints) + "\n") if hints else "")
    topics, dropped = [], []
    for attempt in range(2):                            # a second ask replaces topics dropped by the never-list
        data, result = brain.ask_json("writer", prompt, temperature=0.9)
        if cluster_out is not None and isinstance(data, dict) and not cluster_out:
            cluster_out["hub"] = data.get("hub")
            cluster_out["spokes"] = [x for x in (data.get("spokes") or []) if isinstance(x, dict) and x.get("topic")
                                     and not topic_flags(f"{x.get('topic', '')} {x.get('angle', '')}", mode="topic")
                                     and not franchise_names(x)][:2]
        for t in (data.get("topics") or []):
            if not (isinstance(t, dict) and t.get("topic")) or len(topics) >= n:
                continue
            if _weak(t):                                # 19 Nov: the writer itself rated it below scroll-stop
                log(f"Topic dropped (scroll-stop {t.get('scroll_stop')}): {t.get('topic')}")
                dropped.append(t["topic"])
                continue
            flags = topic_flags(f"{t.get('topic', '')} {t.get('angle', '')}", mode="topic")
            if flags:                                   # owner's rule: never-topics are dropped, not just warned
                log(f"Topic dropped ({', '.join(flags)}): {t.get('topic')}")
                dropped.append(t["topic"])
                continue
            names = franchise_names(t)
            if names:                                   # 20 Nov: the content gate holds these; never make them
                log(f"Topic dropped (protected franchise: {', '.join(names)}): {t.get('topic')}")
                dropped.append(f"{t['topic']} (names a protected franchise: {', '.join(names)})")
                continue
            if ch.get("type") == "story":               # 20 Nov: proof of demand now (engine/topic_proof.py)
                try:
                    from .topic_proof import evidence_text, proof
                    pr = proof(str(t["topic"]), ch, log=log)
                except Exception as e:  # noqa: BLE001 - unmeasured topics are kept (the potential gate judges)
                    log(f"topic proof skipped: {type(e).__name__}: {e}")
                    pr = {"tier": "unknown"}
                t["demand"] = evidence_text(pr) if pr.get("tier") != "unknown" else ""
                if attempt == 0 and pr.get("tier") in ("cold", "none"):
                    log(f"Topic dropped ({t['demand'][:90]}): {t.get('topic')}")
                    dropped.append(f"{t['topic']} ({pr.get('tier')} demand: nobody is watching it now)")
                    continue
            if t["topic"] not in [x["topic"] for x in topics]:
                topics.append(t)
        if len(topics) >= n or not dropped:
            break
        prompt += (f"\n\nWe still need {n - len(topics)} more topics. Do not repeat these: "
                   f"{'; '.join(x['topic'] for x in topics + [{'topic': d} for d in dropped])}")
    log(f"Topics for {ch['name']}: {len(topics)} from {result.provider}")
    return topics[:n]


# ---------- plan ----------

def cluster_slots(slots: list, topics: list[dict], cluster: dict) -> list[dict]:
    """Topics in slot order: the hub topic on the long-video slot, the 2 spokes on the next Short slots after it
    (they can point to the full story), every other topic in order. Without cluster data: unchanged."""
    hub = cluster.get("hub")
    long_i = next((i for i, (_, k) in enumerate(slots) if k == "long"), None)
    if not isinstance(hub, int) or not 0 <= hub < len(topics) or long_i is None:
        return topics
    out: list = [None] * len(slots)
    out[long_i] = dict(topics[hub], role="hub")
    t_long = slots[long_i][0]
    after = [i for i, (w, k) in enumerate(slots) if k != "long" and w > t_long]
    before = [i for i, (w, k) in enumerate(slots) if k != "long" and w < t_long][::-1]
    for sp, i in zip(cluster.get("spokes") or [], after + before):
        out[i] = dict(sp, role="spoke", hub=topics[hub]["topic"])
    rest = [t for j, t in enumerate(topics) if j != hub]
    for i in range(len(out)):
        if out[i] is None:
            out[i] = rest.pop(0) if rest else {}
    return out


def calendar_hints(start: date, days: int = 21) -> dict[str, list[str]]:
    """Events in config/calendar.yaml from `start` to start+days, grouped per channel (topic ideas)."""
    import yaml
    from .config import CONFIG_DIR
    path = CONFIG_DIR / "calendar.yaml"
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    for ev in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("events", []):
        d = ev.get("date")
        d = d if isinstance(d, date) else date.fromisoformat(str(d))
        if start - timedelta(days=1) <= d <= start + timedelta(days=days):
            for ch in ev.get("channels", []):
                out.setdefault(ch, []).append(f"{ev['title']} ({d:%d %b})")
    return out


def plan_week(brain, start: date | None = None, only: list[str] | None = None, memory=None,
              hints: dict[str, list[str]] | None = None, log=print) -> dict:
    start = start or next_monday()
    cal = calendar_hints(start)
    try:                                                    # festivals, holidays, round anniversaries (18 Nov)
        from .events import event_hints
        for c, hs in event_hints(start, log=log).items():
            cal.setdefault(c, []).extend(h for h in hs if h not in cal[c])
    except Exception as e:  # noqa: BLE001
        log(f"events: {e}")
    live = {}
    if brain is not None:
        from .trends import trend_hints
        live = trend_hints(brain, log=log)                  # official feeds only (Wikipedia, Google Trends)
    from .stats_fetch import top_terms                       # what our viewers already search to find us
    searched = {ch["id"]: [f"viewers already find this channel by searching: \"{t}\" (make more on this)"
                           for t, _ in top_terms(ch["id"], 5)] for ch in channels()}
    live = {k: list(live.get(k, [])) + searched.get(k, []) for k in set(live) | {c for c, v in searched.items() if v}}
    keys = set(cal) | set(hints or {}) | set(live)
    hints = {ch: list((hints or {}).get(ch, [])) + live.get(ch, []) + cal.get(ch, []) for ch in keys}
    items, taken = [], []
    for ch in channels():
        if only and ch["id"] not in only and str(ch.get("number")) not in only:
            continue
        if ch.get("active") is False:
            continue
        slots = slots_for(ch, start)
        if not slots:
            continue
        kind_type = ch.get("type")
        topics = []
        if kind_type == "kids":                         # counting lessons from the kids module, never trivia
            from .kids import plan_topics
            topics = plan_topics(len(slots), seed=int(start.strftime("%Y%m%d")), kinds=[k for _, k in slots])
        elif kind_type in BUILDABLE and kind_type != "clips" and brain is not None:
            cluster: dict | None = {} if kind_type == "story" and any(k == "long" for _, k in slots) else None
            try:
                topics = pick_topics(brain, ch, len(slots), memory=memory, hints=(hints or {}).get(ch["id"]),
                                     taken=taken, log=log, cluster_out=cluster)
                taken.extend(t["topic"] for t in topics)
                topics = cluster_slots(slots, topics, cluster or {})
                taken.extend(t["topic"] for t in topics if t.get("role") == "spoke")
            except Exception as e:  # noqa: BLE001 - one channel failing must not stop the week
                log(f"Topics for {ch['name']} failed: {e}")
        try:                                           # 20 Nov: topics the owner picked (engine/picker.py) go first
            from .picker import queued_topics
            picks = queued_topics(ch["id"]) if kind_type in ("story", "brainrot") else []
        except Exception as e:  # noqa: BLE001 - the week is planned without them (they stay in the file)
            log(f"picked topics for {ch['name']}: {type(e).__name__}: {e}")
            picks = []
        short_slots = [i for i, (_w, k) in enumerate(slots) if k == "short"]
        for i, pk in zip(short_slots, picks):
            t = {"topic": pk["topic"], "why": "owner picked this topic", "demand": pk.get("demand") or None,
                 "owner_pick": True}
            if i < len(topics):
                topics[i] = t
            else:
                topics.extend([{}] * (i - len(topics)) + [t])
        promo, promo_idx = None, -1                    # 20 Nov: one value-first promo Short per channel per week
        shorts_idx = [i for i, (_w, k) in enumerate(slots) if k == "short"]
        if shorts_idx and kind_type != "kids":
            try:
                from .product_promo import promo_for
                promo = promo_for(ch["id"], start.isoformat())
                promo_idx = shorts_idx[-1] if promo else -1
            except Exception as e:  # noqa: BLE001 - the week is planned without the promo
                log(f"promo for {ch['name']}: {type(e).__name__}: {e}")
        for i, (when, kind) in enumerate(slots):
            t = topics[i] if i < len(topics) else {}
            items.append({
                "id": f"{when:%m%d_%H%M}_{ch['id']}_{kind}",
                "channel": ch["id"], "channel_name": ch["name"], "number": ch.get("number"),
                "kind": kind, "publish_at": when.isoformat(),
                "topic": t.get("topic"), "angle": t.get("angle"), "why": t.get("why"),
                "role": t.get("role"), "hub": t.get("hub"), "feeling": t.get("feeling"), "now_hook": t.get("now_hook"),
                "demand": t.get("demand") or None, "owner_pick": bool(t.get("owner_pick")) or None,
                "status": "planned" if kind_type in BUILDABLE else "not_built",
                "out_dir": None, "file": None, "error": None, "note": None, "log": None})
            if promo and i == promo_idx and not items[-1].get("owner_pick"):   # never over the owner's own pick
                items[-1]["product"] = promo["pid"]
                if kind_type == "story" and promo.get("angle"):
                    items[-1].update(topic=promo["angle"], angle=None, role=None, hub=None, demand=None,
                                     why=f"helps viewers first; links our {promo['title']}")
    plan = {"start": start.isoformat(), "created": time.time(),
            "items": sorted(items, key=lambda x: (x["publish_at"], x["number"] or 0))}
    if only and (week_dir(start) / "plan.json").exists():  # add/replace these channels, keep everyone else's items
        old = load_plan(start)
        planned = {it["channel"] for it in items}
        keep = [it for it in old["items"] if it["channel"] not in planned]
        plan = dict(old, items=sorted(keep + items, key=lambda x: (x["publish_at"], x["number"] or 0)))
    save_plan(plan)
    return plan


# ---------- make ----------

CLIP_STATE = ROOT / "data" / "state" / "clip_pool.json"
CLIP_POOL_DAYS = 10           # unused clips older than this are dropped (campaigns end, moments go stale)


def _read_sources() -> list[dict]:
    """data/clip_sources.txt, one per line: "<file or direct link> [campaign_id] [channel=<channel id>]"."""
    if not CLIP_SOURCES.exists():
        return []
    out = []
    for line in CLIP_SOURCES.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if not parts or parts[0].startswith("#"):
            continue
        rest = parts[1:]
        chan = next((p.split("=", 1)[1] for p in rest if p.startswith("channel=")), None)
        camp = next((p for p in rest if not p.startswith("channel=")), None)
        out.append({"source": parts[0], "campaign": camp, "channel": chan})
    return out


def clip_state() -> dict:
    """Clip pool shared by all weeks: which sources were already cut (never clip the same footage twice) and the
    finished clips waiting for a slot, per channel (a gaming stream never lands on the podcast channel)."""
    s = json.loads(CLIP_STATE.read_text(encoding="utf-8")) if CLIP_STATE.exists() else {}
    if "used" not in s:                                 # first run: carry over what older week plans recorded
        used = []
        for p in sorted(WEEKS_DIR.glob("*/plan.json")) if WEEKS_DIR.exists() else []:
            try:
                used += json.loads(p.read_text(encoding="utf-8")).get("clip_sources_used") or []
            except Exception:  # noqa: BLE001
                pass
        s = {"used": list(dict.fromkeys(used)), "pool": {}}
    s.setdefault("pool", {})
    try:                                                # PC: footage it cut since the last pull (20 Nov)
        s["used"] = list(dict.fromkeys(s["used"] + json.loads(PC_CLIP_USED.read_text(encoding="utf-8"))))
    except (OSError, ValueError):
        pass
    return s


PC_CLIP_USED = ROOT / "data" / "pc" / "clip_used.json"


def remember_used_on_pc(source: str) -> None:
    """The PC's pulled clip_pool.json is replaced on every pull; this list survives until the cloud has merged."""
    import os
    from .core.where import in_runner
    if in_runner():
        return
    try:
        used = json.loads(PC_CLIP_USED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        used = []
    PC_CLIP_USED.parent.mkdir(parents=True, exist_ok=True)
    PC_CLIP_USED.write_text(json.dumps((used + [source])[-500:]), encoding="utf-8")


PC_CLIP_FAILED = ROOT / "data" / "pc" / "clip_failed.json"


def _count_clip_failure(source: str) -> int:
    """How often this footage failed. The cloud keeps the count in clip_pool.json (state bundle); the PC's copy of that
    file is replaced on every pull, so the PC also keeps its own count (20 Nov: the same footage failed every 6 min
    for hours because the count never reached 2)."""
    from .core.where import in_runner
    s = clip_state()
    fails = s.setdefault("failed", {})
    fails[source] = fails.get(source, 0) + 1
    n = fails[source]
    save_clip_state(s)
    if not in_runner():
        try:
            pc = json.loads(PC_CLIP_FAILED.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pc = {}
        pc[source] = pc.get(source, 0) + 1
        n = max(n, pc[source])
        PC_CLIP_FAILED.parent.mkdir(parents=True, exist_ok=True)
        PC_CLIP_FAILED.write_text(json.dumps(dict(list(pc.items())[-500:])), encoding="utf-8")
    return n


def _skip_source(item: dict, source: str) -> None:
    """Never cut this footage again: cloud state, the PC's own list, and the item (the PC's done marker reports
    `clip_skipped` so the cloud skips it too)."""
    s = clip_state()
    if source not in s["used"]:
        s["used"].append(source)
    save_clip_state(s)
    remember_used_on_pc(source)
    skipped = item.setdefault("clip_skipped", [])
    if source not in skipped:
        skipped.append(source)


def save_clip_state(s: dict) -> None:
    CLIP_STATE.parent.mkdir(parents=True, exist_ok=True)
    CLIP_STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")


def _source_channel(src: dict) -> str | None:
    """Which clip channel a source belongs to: written on the line, else the campaign's suggested account."""
    if src.get("channel"):
        return src["channel"]
    if src.get("campaign"):
        try:
            from . import db
            return (db.get_campaign(db.connect(), src["campaign"]) or {}).get("account")
        except Exception:  # noqa: BLE001
            return None
    return None


def next_source(channel_id: str, used: list[str]) -> dict | None:
    """The first unused source for this channel (or one not tied to any channel)."""
    loose = None
    for s in _read_sources():
        if s["source"] in used:
            continue
        owner = _source_channel(s)
        if owner == channel_id:
            return s
        if owner is None and loose is None:
            loose = s
    return loose


def _live_pool(entries: list[dict]) -> list[dict]:
    cutoff = time.time() - CLIP_POOL_DAYS * 86400
    return [c for c in entries if (c.get("at") or time.time()) > cutoff
            and ((Path(c["out_dir"]) / c["file"]).exists() or c.get("asset"))]


def _pool_local(clip: dict) -> str:
    """Cloud runs start empty: the spare clips live in the cloud copy of the run that cut them (17 Nov: they were lost,
    so every source gave one clip instead of four)."""
    if (Path(clip["out_dir"]) / clip["file"]).exists() or not clip.get("asset"):
        return clip["out_dir"]
    from .cloud import media
    from .cloud.store import Store
    folder = media.ensure_local(Store(), {"id": "pool", "out_dir": clip["out_dir"], "cloud_asset": clip["asset"]})
    if not folder or not (Path(folder) / clip["file"]).exists():
        raise RuntimeError("A spare clip's file is gone from the cloud copy")
    return str(folder)


def has_clip_material(channel_id: str) -> bool:
    s = clip_state()
    return bool(_live_pool(s["pool"].get(channel_id, []))) or next_source(channel_id, s["used"]) is not None


def pool_folders() -> set[Path]:
    """Folders holding clips that still wait for a slot (the cleanup must keep them)."""
    s = clip_state()
    return {Path(c["out_dir"]).resolve() for entries in s["pool"].values() for c in _live_pool(entries)}


GATE_TRIES = 4            # campaign clips: footage tried per slot before giving up (gate holds explicit ones)


def _make_clip(plan: dict, item: dict, brain, ch: dict, memory, log) -> tuple[str, str]:
    """One source video gives many clips; each clip slot of the channel takes the next best one."""
    s = clip_state()
    pool = _live_pool(s["pool"].get(ch["id"], []))
    tries = 0
    while not pool:
        src = next_source(ch["id"], s["used"])
        if not src:
            raise NeedsSource("No clip footage left for this channel. Send /source <link> in Telegram or add a "
                              "line to data/clip_sources.txt")
        from . import clips, db
        campaign = db.get_campaign(db.connect(), src["campaign"]) if src.get("campaign") else None
        try:
            out, metas = clips.make_clips(brain, src["source"], ch, campaign=campaign, memory=memory, keep=4, log=log)
        except clips.UnusableFootage as e:              # never gives a clip: skip it now, try the next footage
            _skip_source(item, src["source"])
            tries += 1
            log(f"   footage skipped ({e}), trying the next clip ({tries}/{GATE_TRIES})")
            if tries >= GATE_TRIES:
                raise RuntimeError(f"{tries} footage clips in a row could not be used; last: {e}") from e
            s = clip_state()
            continue
        except Exception:
            if _count_clip_failure(src["source"]) >= 2:  # a source that fails twice is skipped (bad link, no permission)
                _skip_source(item, src["source"])
            raise
        s = clip_state()
        s["used"].append(src["source"])
        save_clip_state(s)
        remember_used_on_pc(src["source"])
        tries += 1
        # 20 Nov: a campaign clip the gate stops (explicit language, wrong length ...) is useless; the slot tries the
        # next footage instead of handing the owner a held clip (Dom's stream clips are often explicit)
        good = [m for m in metas if not campaign or not (m.get("gate") or {}).get("problems")]
        if campaign and not good:
            log(f"   footage held by the campaign gate, trying the next clip ({tries}/{GATE_TRIES})")
            if tries >= GATE_TRIES:
                raise RuntimeError(f"{tries} footage clips in a row were held by the campaign gate")
            s = clip_state()
            continue
        item["clip_source"] = src["source"]                      # the PC's done marker reports it to the cloud
        asset = f"{item.get('id', 'clip')}.zip"                   # the cloud runner uploads this folder under the item's name
        pool = [{"out_dir": str(out), "file": m["file"], "at": time.time(), "asset": asset} for m in good]
        if not pool:
            raise RuntimeError("The footage gave no usable clips")
    while pool:
        clip = pool.pop(0)
        try:
            out_dir = _pool_local(clip)
        except Exception as e:  # noqa: BLE001 - try the next spare clip
            log(f"spare clip skipped: {e}")
            continue
        s = clip_state()
        s["pool"][ch["id"]] = pool
        save_clip_state(s)
        return out_dir, clip["file"]
    s = clip_state()
    s["pool"][ch["id"]] = []
    save_clip_state(s)
    raise RuntimeError("The spare clips were gone; the next run cuts new ones")


def _refresh_topic(plan: dict, item: dict, ch: dict, brain, memory=None, log=print) -> None:
    """Right before a Short is made: today's trends vs the topic planned days ago; the stronger one is made (owner
    19 Nov: "our content looks outdated, not trending"). The planned topic stays in the plan as planned_topic."""
    try:
        from .trends import trend_hints
        fresh = trend_hints(brain, log=log).get(ch["id"], [])
    except Exception:  # noqa: BLE001
        fresh = []
    planned = f"{item['topic']}" + (f" (angle: {item['angle']})" if item.get("angle") else "")
    blocked = franchise_names(item)                     # planned before the shift-left filter: replace it
    hints = fresh + ([] if blocked else
                     [f"PLANNED EARLIER (keep it only if nothing above beats it on scroll-stop): {planned}"])
    taken = [it.get("topic") for it in plan.get("items", []) if it.get("topic") and it is not item]
    try:
        got = pick_topics(brain, ch, 1, memory=memory, hints=hints, taken=taken, log=log)
    except Exception as e:  # noqa: BLE001 - the planned topic is still fine
        log(f"topic refresh: {type(e).__name__}: {e}")
        return
    item["refreshed"] = True
    if not got:
        return
    t = got[0]
    if t["topic"].strip().lower() != str(item["topic"]).strip().lower():
        item["planned_topic"] = item["topic"]
        log(f"Fresher topic for {ch['name']}: {t['topic']} (was: {item['topic']})")
    item.update(topic=t["topic"], angle=t.get("angle") or item.get("angle"), why=t.get("why") or item.get("why"),
                feeling=t.get("feeling"), now_hook=t.get("now_hook"))


def clip_slot(ch: dict, item: dict) -> bool:
    """20 Nov: a story channel with clips_first (Stream Clips: GTA facts) cuts a campaign clip in its Short slot when
    campaign footage is waiting (Kick clips of a joined campaign). On the PC the used footage is remembered locally
    (PC_CLIP_USED) and reported back in the done marker, so the cloud never cuts the same footage again."""
    if ch.get("type") != "story" or not ch.get("clips_first") or item.get("kind") == "long":
        return False
    s = clip_state()                                    # only footage meant for THIS channel (never loose sources)
    return bool(_live_pool(s["pool"].get(ch["id"], []))) or any(
        src["source"] not in s["used"] and _source_channel(src) == ch["id"] for src in _read_sources())


def story_paused(ch: dict) -> str | None:
    """Why this channel's story Shorts are paused (config `story_pause`), or None. 22 Nov: every Stream Clips GTA fact
    Short names a protected franchise (GTA, Vice City; ip_guard), which the content gate holds, and policy checks
    never relax: the PC failed its 06:30 slot at 05:34 ('Topic dropped (protected franchise: gta)' twice, then 'No
    topic was planned'). Paused, the channel makes nothing that cannot pass; its campaign clip slots still go."""
    return str(ch.get("story_pause") or "").strip() or None


def snack_theme(item: dict) -> str:
    """Brain Snack's theme for a fact/quiz video: the PLANNED idea. 22 Nov: a physics game overwrote the item's topic
    with its own title, a second one overwrote the kept planned topic too, and every remake got that title + the
    angle + the judge's notes about the previous (different) format as its theme: a food quiz came out as 'Venus vs.
    Birthday: Food Edition' with a hook copied from the judge's example. The judge's findings are about the old video
    and are fixed in the formats themselves (on-screen hooks, titles); only the owner's own change request is passed."""
    theme = str(item.get("planned_topic") or item.get("topic") or "").strip()
    if theme and item.get("angle"):
        theme = f"{theme} (angle: {item['angle']})"
    if item.get("status") == "redo" and item.get("note"):
        theme = f"{theme}\nThe owner asked for this change: {item['note']}"
    return theme.strip()


def make_item(plan: dict, item: dict, brain, memory=None, log=print) -> None:
    from .config import channel as get_channel
    ch = get_channel(item["channel"])
    if clip_slot(ch, item):
        log(f"{ch['name']}: campaign footage waiting, this slot becomes a clip")
        item["out_dir"], item["file"] = _make_clip(plan, item, brain, ch, memory, log)
        item["made_as"] = "clip"
        from .training_data import record
        record(item)
        return
    if ch["type"] == "story" and story_paused(ch):
        raise RuntimeError(f"{ch['name']}: story Shorts are paused ({story_paused(ch)}); only campaign clips are made")
    if ch["type"] == "story" and not item.get("topic") and brain is not None:
        # the week plan got fewer topics than slots (AI busy that day): pick one now instead of skipping the slot
        taken = [it.get("topic") for it in plan.get("items", []) if it.get("topic")]
        got = pick_topics(brain, ch, 1, memory=memory, taken=taken, log=log)
        if got:
            item["topic"], item["angle"], item["why"] = got[0]["topic"], got[0].get("angle"), got[0].get("why")
    if ch["type"] == "story" and item.get("topic") and brain is not None and franchise_names(item):
        item["refreshed"] = False                      # a topic the content gate would hold: always replaced
        _refresh_topic(plan, item, ch, brain, memory, log)
        if franchise_names(item):
            raise RuntimeError("The planned topic names a protected franchise "
                               f"({', '.join(franchise_names(item))}) and no replacement topic came; retried later")
        item.pop("gate_note", None)                    # the old video's findings belong to the old topic
    elif ch["type"] == "story" and item.get("kind") != "long" and item.get("topic") and brain is not None \
            and item.get("status") != "redo" and not item.get("refreshed") and item.get("role") not in ("hub", "spoke"):
        _refresh_topic(plan, item, ch, brain, memory, log)
    topic = item.get("topic") or ""
    if item.get("angle"):
        topic = f"{topic} (angle: {item['angle']})"
    if item.get("feeling"):
        topic = f"{topic}\nThe feeling this video must deliver: {item['feeling']}" + (
            f" (why now: {item['now_hook']})" if item.get("now_hook") else "")
    if item.get("status") == "redo" and item.get("note"):
        topic = f"{topic}\nThe owner asked for this change: {item['note']}"
    if item.get("status") == "redo" and item.get("gate_note"):        # 20 Nov: the quality gate's findings
        topic = f"{topic}\nThe last version failed the quality check; fix all of this: {item['gate_note']}"
    if ch["type"] == "story":
        if not item.get("topic"):                      # never write a script about nothing
            raise RuntimeError("No topic was planned for this slot. Run 'python cli.py week plan' again.")
        from . import story
        out, _ = story.make(brain, ch, topic=topic, fmt="long" if item["kind"] == "long" else "short",
                            memory=memory, log=log)
        item["out_dir"], item["file"] = str(out), (sorted(out.glob("*.mp4")) or [Path("")])[0].name
        try:                                           # the hook loop learns which hook type this video used
            from .content_tuning import record_hook
            record_hook(item["id"], ch["id"], json.loads((out / "script.json").read_text(encoding="utf-8"))
                        .get("hook_type"))
        except Exception:  # noqa: BLE001
            pass
    elif ch["type"] == "brainrot":
        from .snack import maker as snack              # Brain Snack v3: five rotating game formats
        if item.get("status") == "redo" and item.get("gate_note"):
            log(f"Brain Snack remake; the last version's findings are fixed in the formats: {item['gate_note'][:160]}")
        out, meta = snack.make(brain, ch, topic=snack_theme(item) or None, memory=memory, log=log)
        item["out_dir"], item["file"] = str(out), (sorted(out.glob("*.mp4")) or [Path("")])[0].name
        if item.get("topic") and not (meta or {}).get("used_topic"):     # a physics game: the plan shows what was
            if not item.get("planned_topic"):                            # made; the planned idea is kept ONCE
                item["planned_topic"] = item["topic"]
            item["topic"] = (meta or {}).get("title") or item["topic"]
        elif (meta or {}).get("used_topic") and item.get("planned_topic"):
            item["topic"] = item["planned_topic"]                        # a fact/quiz video made from the idea
    elif ch["type"] == "clips":
        item["out_dir"], item["file"] = _make_clip(plan, item, brain, ch, memory, log)
    elif ch["type"] == "kids":
        from . import kids
        out, _ = kids.make(brain, ch, topic=topic or None, memory=memory, log=log,
                           fmt="long" if item["kind"] == "long" else "short")
        item["out_dir"], item["file"] = str(out), "video.mp4"
    else:
        raise RuntimeError(f"Channel type '{ch['type']}' has no video maker yet")
    from .training_data import record                  # 19 Nov: our own training set (words now, numbers later)
    record(item)


def make_week(brain, start: date | str | None = None, only_ids: list[str] | None = None, memory=None,
              log=print) -> dict:
    start = start or latest_week()
    if not start:
        raise FileNotFoundError("No plan yet. Run: python cli.py week plan")
    plan = load_plan(start)
    logs = week_dir(plan["start"]) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    todo = [it for it in plan["items"] if it["status"] in TO_MAKE and (not only_ids or it["id"] in only_ids)]
    log(f"Week of {plan['start']}: {len(todo)} videos to make")
    for n, item in enumerate(todo, 1):
        log_path = logs / f"{item['id']}.log"
        with open(log_path, "a", encoding="utf-8") as fh:
            def item_log(msg, _fh=fh):
                line = f"[{time.strftime('%H:%M:%S')}] {msg}"
                _fh.write(line + "\n")
                _fh.flush()
                log(f"  {line}")
            log(f"[{n}/{len(todo)}] {item['channel_name']} {item['kind']} — {item.get('topic') or 'clip'}")
            item["status"], item["log"], item["error"] = "making", str(log_path), None
            save_plan(plan)
            try:
                make_item(plan, item, brain, memory=memory, log=item_log)
                item["status"], item["made_at"] = "made", time.time()
            except NeedsSource as e:
                item["status"], item["error"] = "needs_source", str(e)
            except Exception as e:  # noqa: BLE001 - keep making the rest of the week
                item["status"], item["error"] = "failed", f"{type(e).__name__}: {e}"
                fh.write(traceback.format_exc())
            save_plan(plan)
    return plan


def summary(plan: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in plan["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    return counts


# ---------- decisions ----------

def decide(start: str, item_id: str, action: str, note: str = "") -> dict:
    if action not in DECISIONS:
        raise ValueError(f"Unknown action '{action}'")
    with _LOCK:
        plan = load_plan(start)
        for it in plan["items"]:
            if it["id"] == item_id:
                if it["status"] not in ("made", "approved", "rejected", "redo"):
                    raise ValueError(f"{item_id} is '{it['status']}', only finished videos can be decided")
                it["status"], it["decided_at"] = DECISIONS[action], time.time()
                if note.strip():
                    it["note"] = note.strip()[:1000]
                save_plan(plan)
                return it
    raise KeyError(item_id)


def approved_items(start: str) -> list[dict]:
    """What the uploader may schedule: only videos the owner approved."""
    return [it for it in load_plan(start)["items"] if it["status"] == "approved"]


# ---------- approval page ----------

def _safe_output_path(rel: str) -> Path | None:
    """Only files inside output/ may be served."""
    try:
        path = (OUTPUT_DIR / urllib.parse.unquote(rel)).resolve()
        path.relative_to(OUTPUT_DIR.resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def _item_media(it: dict) -> dict:
    """Video, thumbnails, titles and checks for one item."""
    info = {"video": None, "thumbs": [], "title": "", "titles": [], "description": "", "fact": None, "caption": "",
            "reel": None, "reel_caption": ""}
    if not it.get("out_dir"):
        return info
    out = Path(it["out_dir"])
    rel = lambda p: urllib.parse.quote(p.resolve().relative_to(OUTPUT_DIR.resolve()).as_posix())
    if it.get("file") and (out / it["file"]).exists():
        info["video"] = rel(out / it["file"])
    info["thumbs"] = [rel(p) for p in sorted(out.glob("thumbnail_*.jpg")) + sorted(out.glob("reel_cover.jpg"))]
    stem = (it.get("file") or "video.mp4").replace(".mp4", "")
    for cand, rj in ((out / "reel.mp4", out / "reel.json"), (out / f"{stem}_reel.mp4", out / f"{stem}_reel.json")):
        if cand.exists() and (stem == "video" or cand.name != "reel.mp4"):
            info["reel"] = rel(cand)
            if rj.exists():
                info["reel_caption"] = json.loads(rj.read_text(encoding="utf-8")).get("caption", "")
            break
    meta_path = out / "upload.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        info["title"] = meta.get("title", "")
        info["titles"] = meta.get("title_options") or []
        info["description"] = meta.get("description", "")
        info["fact"] = meta.get("fact_check")
        info["policy"] = meta.get("policy_flags") or []
        info["too_short"] = meta.get("midroll_eligible") is False
    clips_path = out / "clips.json"
    if clips_path.exists():
        for c in json.loads(clips_path.read_text(encoding="utf-8")):
            if c.get("file") == it.get("file"):
                info["title"] = (c.get("hook_options") or [c.get("title", "")])[0]
                info["titles"] = c.get("hook_options") or []
                info["caption"] = c.get("caption", "")
                info["fact"] = {"ok": (c.get("rule_check") or {}).get("passed", True),
                                "problems": [(c.get("rule_check") or {}).get("summary", "")]} if c.get("rule_check") else None
    return info


STATUS_LABEL = {"planned": "⏳ planned", "making": "🛠️ making now", "made": "👀 waiting for you",
                "approved": "✅ approved", "rejected": "❌ rejected", "redo": "✏️ change requested",
                "failed": "⚠️ failed", "needs_source": "📥 needs a source video", "not_built": "🚧 maker not built yet"}


def attention_reasons(it: dict, m: dict) -> list[str]:
    """Why an item needs the owner's eyes before a quick approve ([] = routine)."""
    why = []
    if m.get("fact") and not m["fact"].get("ok"):
        why.append("fact-check found a wrong detail")
    elif m.get("fact") and m["fact"].get("warnings"):
        why.append(f"{len(m['fact']['warnings'])} detail(s) not in the sources")
    if m.get("policy"):
        why.append("touches a never-topic")
    if m.get("too_short"):
        why.append("long video under 8:00 (no mid-roll ads)")
    if it.get("error"):
        why.append("making it failed")
    return why


def render_page(plan: dict, token: str) -> str:
    e = html.escape
    counts = summary(plan)
    days: dict[str, list[dict]] = {}
    for it in plan["items"]:
        days.setdefault(datetime.fromisoformat(it["publish_at"]).strftime("%A %d %B"), []).append(it)
    blocks, attention = [], []
    for day, items in days.items():
        cards = []
        for it in items:
            m = _item_media(it)
            why = attention_reasons(it, m)
            if why:
                attention.append(f"<li><a href='#{e(it['id'])}'>#{it.get('number')} {e(it['channel_name'])} · "
                                 f"{e(it['kind'])} · {e(day)}</a>: {e('; '.join(why))}</li>")
            when = datetime.fromisoformat(it["publish_at"]).strftime("%I:%M %p IST")
            media = (f"<video controls preload='metadata' src='/f/{m['video']}?t={token}'></video>" if m["video"] else "")
            if m.get("reel"):
                media += (f"<p class='why'>Instagram Reel version (different hook, shorter ending):</p>"
                          f"<video controls preload='metadata' src='/f/{m['reel']}?t={token}'></video>")
            thumbs = "".join(f"<img src='/f/{t}?t={token}'>" for t in m["thumbs"])
            fact = ""
            if m["fact"] is not None:
                if not m["fact"].get("ok"):
                    fact = (f"<p class='warn'>❌ Fact-check contradicted (cannot be uploaded until fixed): "
                            f"{e('; '.join(m['fact'].get('problems') or [])[:500])}</p>")
                elif m["fact"].get("warnings"):
                    fact = (f"<p class='warn'>✅ No contradictions · ⚠️ Please check (not in the sources): "
                            f"{e('; '.join(m['fact'].get('warnings') or [])[:500])}</p>")
                else:
                    fact = "<p class='ok'>✅ Checks passed</p>"
            titles = "".join(f"<li>{e(t)}</li>" for t in m["titles"][:3])
            buttons = ""
            if it["status"] in ("made", "approved", "rejected", "redo"):
                buttons = (f"<form method='post' action='/decide?t={token}'>"
                           f"<input type='hidden' name='id' value='{e(it['id'])}'>"
                           f"<textarea name='note' placeholder='What should change? (needed for Change)'>{e(it.get('note') or '')}</textarea>"
                           "<button name='action' value='approve' class='ap'>✅ Approve</button>"
                           "<button name='action' value='redo' class='rd'>✏️ Change</button>"
                           "<button name='action' value='reject' class='rj'>❌ Reject</button>"
                           + ("<button name='action' value='undo'>↩ Undo</button>" if it["status"] != "made" else "")
                           + "</form>")
            err = f"<p class='warn'>{e(it['error'])}</p>" if it.get("error") else ""
            if m.get("policy"):
                err += f"<p class='warn'>❌ Touches a never-topic ({e(', '.join(m['policy']))}): blocked from upload</p>"
            cards.append(
                f"<div class='card {e(it['status'])}' id='{e(it['id'])}'><div class='head'><b>{e(when)}</b> · #{it.get('number')} "
                f"{e(it['channel_name'])} · {e(it['kind'])} · <span class='st'>{STATUS_LABEL.get(it['status'], it['status'])}</span></div>"
                f"<p class='topic'>{e(m['title'] or it.get('topic') or '')}</p>"
                f"<p class='why'>{e(it.get('angle') or '')}</p>{media}<div class='thumbs'>{thumbs}</div>"
                f"{'<ol>' + titles + '</ol>' if titles else ''}{fact}{err}"
                f"<details><summary>Description / caption</summary><pre>{e(m['description'] or m['caption'])}</pre>"
                + (f"<b>Reel caption:</b><pre>{e(m['reel_caption'])}</pre>" if m.get("reel_caption") else "") + "</details>"
                f"{buttons}</div>")
        blocks.append(f"<h2>{e(day)}</h2><div class='grid'>{''.join(cards)}</div>")
    chips = " · ".join(f"{STATUS_LABEL.get(k, k)}: {v}" for k, v in sorted(counts.items()))
    story_channels = sorted({it["channel_name"] for it in plan["items"] if it["kind"] in ("short", "long")
                             and it["channel"] not in ("brain_snack", "bloop_and_friends")})
    checklist = [
        "After each upload goes live: pin a question as the first comment (not on the kids channel).",
        "On each Short: add the 'related video' link to its long video (YouTube Studio > Short > Related video).",
        "Share each new Reel to your Instagram Story once.",
        "Once this week on each story channel, a YouTube Post or poll: " + (", ".join(story_channels) or "none"),
        "Hot Take HQ: submit each clip link on Content Rewards within 30 minutes of posting.",
        "Send 5 LinkedIn messages to podcasters/founders with a free sample clip (retainer clients).",
    ]
    checklist_html = "".join(f"<li>{e(x)}</li>" for x in checklist)
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Week of {e(plan['start'])} — approve videos</title><style>
body{{background:#0e0e10;color:#eee;font-family:Segoe UI,Roboto,sans-serif;margin:16px}}
h1{{font-size:20px}} h2{{font-size:17px;margin:22px 0 8px;color:#ffd400}}
.grid{{display:flex;flex-wrap:wrap;gap:14px}} .card{{background:#1b1b1f;border-radius:12px;padding:12px;width:360px}}
.card.approved{{outline:2px solid #2ecc71}} .card.rejected{{opacity:.55}} .card.redo{{outline:2px solid #f39c12}}
video{{width:100%;max-height:560px;border-radius:8px;background:#000}} .thumbs img{{width:48%;margin:4px 1% 0 0;border-radius:6px}}
.head{{font-size:13px;color:#bbb}} .topic{{font-weight:600;margin:6px 0 2px}} .why{{color:#aaa;font-size:13px;margin:0 0 8px}}
.ok{{color:#2ecc71}} .warn{{color:#f39c12}} pre{{white-space:pre-wrap;font-size:12px;color:#ccc}}
textarea{{width:100%;min-height:44px;margin-top:8px;background:#111;color:#eee;border:1px solid #333;border-radius:6px}}
button{{margin:6px 6px 0 0;padding:8px 12px;border-radius:8px;border:0;font-size:14px;cursor:pointer}}
.ap{{background:#2ecc71}} .rd{{background:#f39c12}} .rj{{background:#e74c3c;color:#fff}}</style></head><body>
<h1>Week of {e(plan['start'])}: approve each video</h1><p>Nothing is posted from this page. Only videos you approve
can be scheduled. "Change" makes the video again using your note.</p><p>{e(chips)}</p>
{("<div class='card'><b>⚠️ Look at these first (" + str(len(attention)) + ")</b> — everything else is routine and "
  "can be approved in one tap:<ul>" + ''.join(attention) + "</ul></div>") if attention else
 "<p class='ok'>✅ Nothing flagged: every video passed its checks.</p>"}
<details open><summary><b>Your manual steps this week</b></summary><ul>{checklist_html}</ul></details>
{''.join(blocks)}</body></html>"""


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # no packet is sent; just picks the LAN interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_handler(start: str, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):           # keep the console quiet
            pass

        def _authed(self, query: dict) -> bool:
            if secrets.compare_digest((query.get("t") or [""])[0], token):
                return True
            self.send_error(403, "Wrong or missing access key")
            return False

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if not self._authed(query):
                return
            if url.path == "/":
                body = render_page(load_plan(start), token).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif url.path.startswith("/f/"):
                path = _safe_output_path(url.path[3:])
                if not path:
                    return self.send_error(404)
                self._send_file(path)
            else:
                self.send_error(404)

        def _send_file(self, path: Path):
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            start_b, end_b = 0, size - 1
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start_b = int(rng.group(1))
                    end_b = int(rng.group(2)) if rng.group(2) else size - 1
                else:                          # "bytes=-N": the last N bytes
                    start_b = max(size - int(rng.group(2)), 0)
                end_b = min(end_b, size - 1)
                if start_b > end_b:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start_b}-{end_b}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end_b - start_b + 1))
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start_b)
                left = end_b - start_b + 1
                try:
                    while left > 0:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    pass                       # the browser stopped reading (seeking): fine

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            if not self._authed(urllib.parse.parse_qs(url.query)) or url.path != "/decide":
                return
            length = min(int(self.headers.get("Content-Length") or 0), 20_000)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            item_id, action = (form.get("id") or [""])[0], (form.get("action") or [""])[0]
            note = (form.get("note") or [""])[0]
            try:
                if action == "redo" and not note.strip():
                    raise ValueError("Write what should change before pressing Change")
                decide(start, item_id, action, note)
            except (KeyError, ValueError) as err:
                return self.send_error(400, str(err))
            self.send_response(303)
            self.send_header("Location", f"/?t={token}#{urllib.parse.quote(item_id)}")
            self.end_headers()

    return Handler


def serve(start: str | None = None, lan: bool = False, port: int = 8765, open_browser: bool = True) -> None:
    start = start or latest_week()
    if not start:
        raise FileNotFoundError("No plan yet. Run: python cli.py week plan")
    load_plan(start)
    token = secrets.token_urlsafe(18)
    host = "0.0.0.0" if lan else "127.0.0.1"
    server = ThreadingHTTPServer((host, port), make_handler(start, token))
    local = f"http://127.0.0.1:{port}/?t={token}"
    print(f"Approval page for the week of {start}:\n  On this PC: {local}")
    if lan:
        print(f"  On your phone (same Wi-Fi): http://{_lan_ip()}:{port}/?t={token}")
    print("Keep this window open while you review. Press Ctrl+C to stop.")
    if open_browser:
        import webbrowser
        webbrowser.open(local)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
