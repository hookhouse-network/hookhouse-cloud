"""Upcoming festivals, holidays and anniversaries, found by themselves (owner, 18 Nov 2026: "pick hot trending
relevant topics ... their calendar, upcoming festivals, events ... nostalgia").

config/calendar.yaml was typed by hand and runs out. Two free, official sources keep it going for ever:
1. Holidays and festivals: the `holidays` library (MIT; government holiday lists incl. optional and religious
   festivals) for the US and India, any year. US holidays go to US channels, Indian festivals to Indian channels,
   kid-friendly celebrations to the kids channel.
2. Anniversaries: Wikipedia's "On this day" feed (Wikimedia REST API, CC BY-SA, no key): events of the planned week
   that turn a round number of years (10, 20, 25, 30, 40, 50, 75, 100 ...) this year: "25 years ago this week".
   Nostalgia is one of the strongest hooks (research_notes, 10 Nov); each one goes to the channels whose niche it
   matches by keywords.
The planner (weekly.plan_week) adds these to the calendar hints; the AI topic picker uses only what truly fits and
the never-topics list still filters everything.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

ROUND = {10, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250}
KIDS_DAYS = re.compile(r"christmas|halloween|valentine|easter|thanksgiving|new year|groundhog|patrick|diwali|deepavali|"
                       r"holi\b|children|mother|father|earth day", re.I)
SKIP = re.compile(r"estimated|shaheedi|martyrdom|muharram|good friday", re.I)       # solemn days: not content hooks
ROUTES = [  # anniversary keywords -> channels
    (r"murder|disappear|vanish|kidnap|heist|robbery|serial killer|mystery|shipwreck|sank|crash|explosion|ghost",
     ["unsolved_after_dark"]),
    (r"championship|world series|super bowl|olympic|nba|nfl|world cup|stanley cup|boxing|marathon|tennis|golf",
     ["clutch_tales"]),
    (r"cricket|test match|ODI|T20|wicket", ["cricket_ke_kisse"]),
    (r"film|movie|oscar|box office", ["ending_decoded"]),
    (r"bollywood|hindi film|indian film", ["picture_abhi_baaki_hai"]),
    (r"india|indian (?!ocean)|mughal|maratha|gandhi|delhi|bengal|maharaja", ["itihaas_ke_raaz"]),
    (r"stock|bank|dollar|economy|market crash|company|apple|microsoft|google|amazon|bitcoin|invent", ["money_cheat_codes"]),
    (r"space|moon|mars|satellite|apollo|nasa|astronaut|telescope|comet|planet|rocket", ["cosmos_unboxed"]),
    (r"ocean|sea|submarine|titanic|whale|reef|tsunami", ["deep_blue_files"]),
    (r"animal|zoo|species|wildlife|dinosaur|fossil", ["wild_instinct"]),
    (r"album|song|video game|toy|television|tv show|cartoon|first .*(phone|email|website)", ["brain_snack"]),
]
# whole words only (18 Nov: "odi" matched inside "sodium", "india" inside "Indian Ocean"); plurals allowed
ROUTES = [(re.compile(r"\b(?:" + rx + r")(?:s|es|ed|d|ing)?\b", re.I), chans) for rx, chans in ROUTES]


def holiday_hints(start: date, days: int = 21) -> dict[str, list[str]]:
    try:
        import holidays
    except ImportError:
        return {}
    from .config import channels
    end = start + timedelta(days=days)
    years = sorted({start.year, end.year})
    by_market: dict[str, list[tuple[date, str]]] = {}
    for market in ("US", "IN"):
        try:
            cal = holidays.country_holidays(market, years=years,
                                            categories=holidays.country_holidays(market).supported_categories)
        except Exception:  # noqa: BLE001
            cal = holidays.country_holidays(market, years=years)
        rows = []
        for d, n in sorted(cal.items()):
            if start - timedelta(days=1) <= d <= end:
                parts = [x.strip() for x in n.split(";") if x.strip() and not SKIP.search(x)]
                if parts:
                    rows.append((d, "; ".join(parts)))
        by_market[market] = rows
    out: dict[str, list[str]] = {}
    for ch in channels():
        if ch.get("type") == "clips":
            continue                                  # campaign / stream clips: footage decides the topic
        if ch.get("type") == "kids":
            evs = [(d, n) for m in by_market.values() for d, n in m if KIDS_DAYS.search(n)]
        else:
            evs = by_market.get(ch.get("market", "US"), [])
        seen = set()
        for d, n in evs:
            key = n.split(";")[0].strip()
            if key not in seen:
                seen.add(key)
                out.setdefault(ch["id"], []).append(f"{key} ({d:%d %b})")
    return out


def anniversary_hints(start: date, days: int = 7, session=None, log=print) -> dict[str, list[str]]:
    import requests
    session = session or requests
    out: dict[str, list[str]] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        try:
            r = session.get(f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/selected/{d.month:02d}/{d.day:02d}",
                            headers={"User-Agent": "HookHouse-planner/1.0"}, timeout=20)
            r.raise_for_status()
            items = r.json().get("selected") or []
        except Exception as e:  # noqa: BLE001 - a missing day just gives fewer ideas
            log(f"on this day {d}: {e}")
            continue
        for it in items:
            yr = it.get("year")
            if not isinstance(yr, int) or (d.year - yr) not in ROUND:
                continue
            text = re.sub(r"\s+", " ", str(it.get("text", ""))).strip()
            hint = f"{d.year - yr} years ago ({d:%d %b} {yr}): {text[:160]}"
            for rx, chans in ROUTES:
                if rx.search(text):
                    for c in chans:
                        if len(out.setdefault(c, [])) < 3:
                            out[c].append(hint)
    return out


def event_hints(start: date, days: int = 21, log=print) -> dict[str, list[str]]:
    out = holiday_hints(start, days)
    try:
        for c, hs in anniversary_hints(start, 7, log=log).items():
            out.setdefault(c, []).extend(hs)
    except Exception as e:  # noqa: BLE001
        log(f"anniversaries: {e}")
    return out
