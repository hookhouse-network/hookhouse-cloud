"""Posting times: US channels post in US peak hours, Indian channels in Indian peak hours."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import settings


def next_slots(market: str, count: int = 3, after: datetime | None = None,
               slots: list[str] | None = None, tz: str | None = None) -> list[datetime]:
    """Next `count` posting times (in IST) for a market ('US' or 'IN')."""
    cfg = settings()
    zone = ZoneInfo(tz or cfg["timezone"])
    slots = slots or cfg["posting_slots"][market]
    after = (after or datetime.now(zone)).astimezone(zone)
    times = sorted(tuple(map(int, s.split(":"))) for s in slots)
    result, day = [], after.date()
    while len(result) < count:
        for h, m in times:
            t = datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
            if t > after:
                result.append(t)
                if len(result) == count:
                    break
        day += timedelta(days=1)
    return result
