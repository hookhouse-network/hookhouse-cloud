"""P9 (27 Nov): no silently swallowed errors. Code that deliberately carries on after an error (an optional extra,
a best-effort cleanup) calls noted(where, error) instead of a bare `pass`: the error becomes a ledger event
('swallowed', at most a few per place per hour), so a hidden recurring failure shows up in the event log instead of
nowhere. noted() never raises and never changes the caller's control flow."""
from __future__ import annotations

import time

_SEEN: dict[str, list[float]] = {}
PER_HOUR = 3                                   # events per place per hour (the rest are counted, not stored)


def noted(where: str, error: BaseException | None = None) -> None:
    try:
        now = time.time()
        hits = [t for t in _SEEN.get(where, []) if now - t < 3600]
        hits.append(now)
        _SEEN[where] = hits
        if len(hits) > PER_HOUR:
            return
        from . import ledger
        ledger.event("swallowed", data={"where": where, "error": f"{type(error).__name__}: {str(error)[:200]}"
                                        if error is not None else ""})
    except Exception as e2:  # noqa: BLE001 - the last sink: print, never raise into the caller
        print(f"noted({where}) failed: {type(e2).__name__}")
