"""Fresh topics (owner, 23 Nov 2026: "you are taking too old trending topics we can do better, and can be popular
content across the platforms").

The trend radar (engine/trends.py: Wikipedia pageview spikes en/hi, Google Trends daily RSS US/IN, YouTube
mostPopular) fed the WEEKLY plan as hints, once, at the start of the week: by the time a slot was made its topic was
days old, and many slots were evergreen picks justified by yearly search volume (an 1897 ghost trial, the Carrington
Event, the barreleye fish). Now every planned story slot made in the next `window_h` hours is offered that day's
on-brand trends once: one AI call keeps the planned topic or switches to a trend that makes a stronger, true,
on-brand video now. The old topic stays on the item (planned_topic) and the switch is logged.
settings.yaml fresh_topics: {enabled, window_h}."""
from __future__ import annotations

import time
from datetime import timedelta

PROMPT = """You plan a {kind} video for the channel "{channel}" ({niche}).
Planned topic (picked on the week's first day): {topic}
Planned angle: {angle}
What people are looking up TODAY that fits this channel:
{trends}

Switch only if one of today's items makes a stronger video for this channel NOW: on-brand, a true story with a person
or a clear event at its centre, more likely to be watched and shared today on YouTube, Instagram and Facebook than
the planned topic, and safe (no fresh tragedy, no politics, no allegation about a living person). Otherwise keep.
Never a topic another video of this channel already has: {taken}{repeat}
Reply JSON only: {{"decision": "keep|switch", "topic": "the video topic", "angle": "the angle in one line",
"why": "why now, in one line", "feeling": "{feelings}"}}"""
REPEAT_LINE = "\nThe planned topic repeats another video of this channel ({twin}): switch to a different topic."


def _cfg() -> dict:
    from .config import settings
    try:
        c = settings().get("fresh_topics") or {}
    except Exception:  # noqa: BLE001
        c = {}
    return {"enabled": bool(c.get("enabled", True)), "window_h": float(c.get("window_h", 36))}


def freshen_due(brain, hints: dict | None = None, now=None, log=print) -> int:
    """Offer today's on-brand trends to every planned story slot made within window_h hours (each slot once a day).
    Returns how many slots switched to a fresh topic."""
    cfg = _cfg()
    if not cfg["enabled"] or brain is None:
        return 0
    from . import autopilot
    from .config import channel as channel_cfg
    from .weekly import FEELINGS, topic_repeats
    if hints is None:
        from . import trends
        hints = trends.trend_hints(brain, log=log)
    now = now or autopilot._now()
    today = now.date().isoformat()
    switched = 0
    window = list(autopilot.items(0, 3))
    topics: dict[str, dict[str, str]] = {}          # channel -> item id -> its topic now (switches update it)
    for _start, o in window:
        if o.get("topic") and o.get("status") != "rejected":
            topics.setdefault(o.get("channel"), {})[o["id"]] = str(o["topic"])
    for start, it in window:
        if it.get("status") != "planned" or it.get("kind") not in ("short", "long") or it.get("fresh_day") == today:
            continue
        when = autopilot._when(it)
        if not (now <= when <= now + timedelta(hours=cfg["window_h"])):
            continue
        tips = [str(t) for t in (hints.get(it["channel"]) or []) if str(t).strip()]
        if not tips:
            continue
        others = [t for iid, t in topics.get(it["channel"], {}).items() if iid != it["id"]]
        twin = topic_repeats(it.get("topic") or "", others)
        try:
            ch = channel_cfg(it["channel"])
            data, _ = brain.ask_json("writer", PROMPT.format(
                kind="long" if it.get("kind") == "long" else "short", channel=ch.get("name", it["channel"]),
                niche=ch.get("niche", ""), topic=it.get("topic") or "", angle=it.get("angle") or "",
                trends="\n".join(f"- {t}" for t in tips[:5]), feelings="|".join(FEELINGS),
                taken="; ".join(o[:80] for o in others[:12]) or "none",
                repeat=REPEAT_LINE.format(twin=twin[:80]) if twin else ""), temperature=0.3)
        except Exception as e:  # noqa: BLE001 - the planned topic stays (said, never silent)
            log(f"fresh topics: {it['id']} kept ({type(e).__name__}: {str(e)[:80]})")
            continue
        fields = {"fresh_day": today}
        if isinstance(data, dict) and data.get("decision") == "switch" and str(data.get("topic") or "").strip():
            dup = topic_repeats(str(data["topic"]), others)
            if dup:                                  # 24 Nov: two Itihaas slots switched to the same trend
                log(f"fresh topics: {it['id']} kept (the switch '{str(data['topic'])[:60]}' repeats '{dup[:60]}')")
                autopilot.update_item(start, it["id"], **fields)
                continue
            feeling = str(data.get("feeling") or "").strip().lower()
            why = str(data.get("why") or "")[:300]
            # 24 Nov: the new topic's own hook and feeling, never the replaced topic's
            fields.update(topic=str(data["topic"])[:200], angle=str(data.get("angle") or "")[:300],
                          why=why, fresh_at=time.time(), planned_topic=it.get("planned_topic") or it.get("topic"),
                          now_hook=why or None, feeling=feeling if feeling in FEELINGS else None)
            topics.setdefault(it["channel"], {})[it["id"]] = fields["topic"]
            switched += 1
            log(f"fresh topics: {it['id']}: '{it.get('topic')}' -> '{fields['topic']}' ({fields['why'][:80]})")
        autopilot.update_item(start, it["id"], **fields)
    return switched
