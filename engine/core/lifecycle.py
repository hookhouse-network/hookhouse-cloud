"""The one place that defines a video's life (docs/ARCHITECTURE.md, phase 1).

Before 20 Nov 2026 a plan item's status was changed in 77 places across 20 files with no shared rules, so videos got
stuck ("making" for ever), skipped, or re-made after posting, and nobody could tell how an item got where it is.
Every status change still ends in weekly.save_plan(); that function now calls `audit()` with the plan before and
after, so every transition is checked against TRANSITIONS and written to the event log (engine/core/ledger.py).

Mode "enforce" (default since 27 Nov: 655 cloud changes, 0 illegal): an illegal transition raises IllegalTransition
before anything is saved. Mode "observe" (LIFECYCLE_MODE=observe, the old default): an illegal transition is logged and reported to the heal queue but still saved, so production
cannot break while the rules are learned from real traffic. Once a week passes with no violations, MODE becomes
"enforce" and illegal transitions raise IllegalTransition before anything is saved."""
from __future__ import annotations

import os

STATES = {
    "not_built": "the channel type has no maker yet",
    "planned": "slot + topic chosen, nothing made",
    "making": "a worker is making it",
    "made": "video exists, waiting for the owner",
    "needs_source": "clip channel without footage",
    "failed": "making failed (retried while attempts remain)",
    "redo": "owner asked for a change; to be made again",
    "approved": "owner approved; scheduled / waiting for its slot",
    "rejected": "owner rejected",
    "posted": "live on at least one platform",
    "missed": "its slot passed and it was not remade",
}
TERMINAL = {"posted", "rejected", "missed"}

_MAKE_AGAIN = {"making", "planned", "missed", "failed", "needs_source"}
TRANSITIONS: dict[str | None, set[str]] = {
    None: {"planned", "not_built"},                       # a new plan item
    "not_built": {"planned", "missed"},
    "planned": _MAKE_AGAIN | {"made", "not_built"},       # made: the PC maker hands a finished video over
    "making": {"made", "failed", "needs_source", "planned", "redo", "missed"},   # planned: stuck worker reset
    "failed": _MAKE_AGAIN | {"made"},
    "needs_source": _MAKE_AGAIN | {"made"},
    "redo": {"making", "failed", "made", "missed", "needs_source", "planned"},
    "made": {"approved", "rejected", "redo", "making", "missed", "posted", "planned"},
    "approved": {"posted", "made", "redo", "rejected", "failed", "missed"},  # made: owner tapped undo
    "rejected": {"made", "redo", "planned"},              # undo / try again
    "posted": {"posted"},
    "missed": {"planned", "making", "made", "failed", "redo"},   # an overdue video is still made (runner, 18 Nov)
}


class IllegalTransition(RuntimeError):
    pass


def mode() -> str:
    # 27 Nov (P9): 655 cloud status changes, 0 illegal; the 4 unlisted transitions were test shortcuts (fixed)
    return os.environ.get("LIFECYCLE_MODE", "enforce")


def allowed(old: str | None, new: str) -> bool:
    return old == new or new in TRANSITIONS.get(old, set())


def diff(before: dict | None, after: dict) -> list[dict]:
    """Status changes between two versions of one plan: [{item, channel, old, new, ok}]."""
    old = {it["id"]: it.get("status") for it in (before or {}).get("items", [])}
    out = []
    for it in after.get("items", []):
        o, n = old.get(it["id"]), it.get("status")
        if o != n:
            out.append({"item": it["id"], "channel": it.get("channel", ""), "old": o, "new": n,
                        "ok": allowed(o, n), "error": (it.get("error") or "")[:300] if n == "failed" else ""})
    return out


def audit(before: dict | None, after: dict, log_event=None, report=None) -> list[dict]:
    """Check + record every status change of one save. Raises IllegalTransition in enforce mode."""
    changes = diff(before, after)
    bad = [c for c in changes if not c["ok"]]
    if bad and mode() == "enforce":
        raise IllegalTransition("; ".join(f"{c['item']}: {c['old']} -> {c['new']}" for c in bad))
    for c in changes:
        if log_event:
            log_event("item.status", item=c["item"], channel=c["channel"],
                      data={"old": c["old"], "new": c["new"], "ok": c["ok"], "error": c["error"]})
        if not c["ok"] and report:
            report("lifecycle", f"illegal status change {c['old']} -> {c['new']}", channel=c["channel"])
    return changes
