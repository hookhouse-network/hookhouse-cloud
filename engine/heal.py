"""Self-healing (owner, 18 Nov 2026: "the system must heal and improve itself; if a fix needs code changes, put it
in high priority and tell me in Telegram, so I can tell Claude 'Heal and Improve the system'").

Every part of the system reports trouble here with `report(area, error)`. Each problem gets a stable signature
(numbers, ids and URLs removed), so the same failure on 14 channels or 6 runs is ONE entry with a counter.

What happens to a problem:
1. Known, self-fixing causes (a free daily limit, a network blip, a 5xx from a platform) are only counted: the
   makers already wait and retry.
2. Causes only the owner can fix (a login expired, a permission missing, a consent screen) become a to-do with the
   exact step, sent once.
3. Anything else that repeats (CODE_AFTER times, or on CODE_CHANNELS channels) is a code problem: it goes into
   the heal queue with high priority, and Telegram says "tell Claude: Heal and Improve the system".
   `python cli.py heal` prints the queue as a brief for Claude (it pulls a read-only copy of the cloud memory).
Improvements found by the daily review (weak hooks, a slot that never works, a format that loses viewers) are
queued too, with priority "improve", so the same Claude prompt picks them up.

Stored in data/state/heal_queue.json (inside the encrypted cloud memory bundle).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .config import ROOT

QUEUE = ROOT / "data" / "state" / "heal_queue.json"
CODE_AFTER = 3                 # the same unexplained failure this many times -> needs a code fix
CODE_CHANNELS = 2              # ... or on this many channels at once
REMIND_H = 24                  # an open code problem is re-announced at most once a day
KEEP_DAYS = 30                 # fixed entries are forgotten after this

# cause -> (kind, plain-language next step). kind: self = retries by itself, owner = owner must act.
KNOWN = [
    (r"daily (free )?limit|quota|429|rate.?limit|too many requests|RESOURCE_EXHAUSTED|NoPictures|neurons",
     "self", "A free daily limit. The system waits for the reset and continues."),
    (r"timed? ?out|ConnectionError|ConnectTimeout|ReadTimeout|RemoteDisconnected|temporarily|50[234]|"
     r"Service Unavailable|Bad Gateway",
     "self", "A network or platform blip. Retried automatically."),
    (r"invalid_grant|token (has )?expired|expired token|Session has expired|OAuthException.*(190|463|467)|"
     r"unauthori[sz]ed|401", "owner",
     "The login for this account expired. Open Telegram > Setup and reconnect it (one tap on the consent screen)."),
    (r"MISSING_PERMISSIONS|insufficient.?(permission|scope)|requires? .*permission|\(#10\)|\(#200\)",
     "owner", "This account is missing a permission. Reconnect it from Telegram > Setup and allow every box."),
    (r"consent|terms of service|accept the terms|Join Campaign", "owner",
     "A terms / consent screen waits for your tap."),
]

_SIG_SUBS = [(re.compile(r"https?://\S+"), "<url>"),
             (re.compile(r"\b(?=[A-Za-z_\-]*\d)(?=[\d_\-]*[A-Za-z])[A-Za-z0-9_\-]{8,}\b"), "<id>"),   # video/item ids
             (re.compile(r"\d+"), "#"), (re.compile(r"\s+"), " ")]


def signature(area: str, error: str) -> str:
    s = str(error)[:300]
    for rx, rep in _SIG_SUBS:
        s = rx.sub(rep, s)
    return f"{area}: {s.strip()[:160]}"


def classify(error: str) -> tuple[str, str]:
    for rx, kind, step in KNOWN:
        if re.search(rx, str(error), re.I):
            return kind, step
    return "code", "Unexplained failure: needs a look at the code."


def _load() -> dict:
    try:
        return json.loads(QUEUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": {}}


def _save(q: dict) -> None:
    from .core.atomic import write_json                  # 20 Nov: crash-safe
    write_json(QUEUE, q)


def report(area: str, error, channel: str = "", platform: str = "", now: float | None = None) -> dict:
    """Count one failure. Returns the queue entry (its 'kind' says who fixes it)."""
    from .cloud.runner import redact
    now = now or time.time()
    err = redact(str(error))
    kind, step = classify(err)
    sig = signature(area, err)
    q = _load()
    it = q["items"].setdefault(sig, {"area": area, "kind": kind, "step": step, "first": now, "n": 0,
                                     "channels": [], "platforms": [], "status": "open", "priority": "normal"})
    it.update(last=now, error=err[:400])
    it["n"] += 1
    if it.get("status") == "fixed":                      # it came back: open again
        it["status"], it["priority"] = "open", "normal"
    for key, val in (("channels", channel), ("platforms", platform)):
        if val and val not in it[key]:
            it[key].append(val)
    if kind == "code" and (it["n"] >= CODE_AFTER or len(it["channels"]) >= CODE_CHANNELS):
        it["priority"] = "high"
    _save(q)
    return it


def improve(key: str, area: str, finding: str, suggestion: str, evidence: str = "", channel: str = "",
            platform: str = "", now: float | None = None) -> dict:
    """An improvement the daily review found (not a crash). Same queue, priority 'improve'."""
    now = now or time.time()
    q = _load()
    sig = f"improve:{key}"
    it = q["items"].setdefault(sig, {"area": area, "kind": "improve", "first": now, "n": 0, "channels": [],
                                     "platforms": [], "status": "open", "priority": "improve"})
    it.update(last=now, error=finding[:400], step=suggestion[:400], evidence=evidence[:600])
    it["n"] += 1
    if it.get("status") == "fixed":
        it["status"] = "open"
    for k, val in (("channels", channel), ("platforms", platform)):
        if val and val not in it[k]:
            it[k].append(val)
    _save(q)
    return it


def resolve(prefix: str, now: float | None = None) -> int:
    """Mark entries whose signature starts with `prefix` fixed (a step worked again, Claude shipped a fix)."""
    q, n = _load(), 0
    for sig, it in q["items"].items():
        if sig.startswith(prefix) and it.get("status") != "fixed":
            it["status"], it["fixed_at"] = "fixed", now or time.time()
            n += 1
    if n:
        _save(q)
    return n


def open_items(priority: str | None = None) -> list[tuple[str, dict]]:
    q = _load()
    out = [(s, it) for s, it in q["items"].items() if it.get("status") == "open"
           and (priority is None or it.get("priority") == priority)]
    order = {"high": 0, "improve": 1, "normal": 2}
    return sorted(out, key=lambda x: (order.get(x[1].get("priority"), 3), -x[1].get("n", 0)))


def notify_due(send=None, now: float | None = None) -> list[str]:
    """Telegram: new / still-open high-priority code problems (once a day each), owner to-dos once.
    Improvements are listed in the daily review instead (no extra pings)."""
    if send is None:
        from .telegram_bot import notify as send
    now = now or time.time()
    q = _load()
    high, owner = [], []
    for sig, it in q["items"].items():
        if it.get("status") != "open":
            continue
        if it.get("priority") == "high" and now - float(it.get("told", 0)) >= REMIND_H * 3600:
            high.append(it)
            it["told"] = now
        elif it.get("kind") == "owner" and it["n"] >= 2 and not it.get("told"):
            owner.append(it)
            it["told"] = now
    for sig in [s for s, it in q["items"].items() if it.get("status") == "fixed"
                and now - float(it.get("fixed_at", now)) > KEEP_DAYS * 86400]:
        q["items"].pop(sig)
    _save(q)
    sent = []
    if high:
        lines = "\n".join(f"• {it['area']}: {it['error'][:140]} ({it['n']}x"
                          + (f", {len(it['channels'])} channels" if it["channels"] else "") + ")" for it in high[:6])
        send("🚨 HIGH PRIORITY: the system needs a code fix it can't make by itself.\n" + lines +
             "\n\nTell Claude on the PC:  Heal and Improve the system")
        sent.append("high")
    for it in owner[:4]:
        where = ", ".join(it["channels"] or it["platforms"]) or it["area"]
        send(f"🔧 Needs you ({where}): {it['step']}")
        sent.append("owner")
    return sent


def brief(items: list[tuple[str, dict]] | None = None) -> str:
    """The queue as a work brief for Claude ('Heal and Improve the system')."""
    items = open_items() if items is None else items
    if not items:
        return "Heal queue is empty: nothing open."
    out = ["# Heal and Improve: open items (highest first)", ""]
    for sig, it in items:
        when = time.strftime("%d %b %H:%M", time.localtime(it.get("last", 0)))
        out += [f"## [{it.get('priority')}] {it['area']}  ({it['n']}x, last {when})",
                f"- kind: {it.get('kind')}  channels: {', '.join(it.get('channels') or []) or '-'}  "
                f"platforms: {', '.join(it.get('platforms') or []) or '-'}",
                f"- error/finding: {it.get('error', '')}", f"- next step: {it.get('step', '')}"]
        if it.get("evidence"):
            out.append(f"- evidence: {it['evidence']}")
        out += [f"- signature: `{sig}`", ""]
    return "\n".join(out)


def from_publish_log(since: float, log_path: Path | None = None) -> int:
    """Feed today's failed uploads into the queue (the post report already told the owner about each one)."""
    from .publish import LOG
    p = log_path or LOG
    if not p.exists():
        return 0
    n, failed, worked = 0, {}, {}
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(line)
        except ValueError:
            continue
        at, plat = float(a.get("at") or 0), a.get("platform")
        if at < since or (a.get("details") or {}).get("dry_run"):
            continue
        if a.get("done"):
            worked[plat] = max(worked.get(plat, 0.0), at)
            continue
        err = (a.get("result") or {}).get("error")
        if err:
            report(f"upload:{plat}", err, channel=a.get("channel", ""), platform=plat or "")
            failed[plat] = max(failed.get(plat, 0.0), at)
            n += 1
    for plat, at in worked.items():                     # 19 Nov: a later real post on that platform = the path works
        if at > failed.get(plat, 0.0):
            resolve(f"upload:{plat}: ")
    return n
