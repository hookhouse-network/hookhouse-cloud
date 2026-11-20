"""Join a campaign from inside OUR system (owner 20 Nov: "the join should be done through the system that we build
because i am accessing that only"). The owner's tap on [Join] in Telegram / the Control Center is the consent; the
system then presses "Join Campaign" on the campaign page in the HookHouse Chrome (the PC that holds the signed-in
profile) and reports what it found.

Order (fail closed):
  1. footage confirmed BEFORE joining (picker.footage_check must be 'ok'), else refused;
  2. the owner's consent is recorded (ledger event campaign.join_consent, with who and when);
  3. scripts.cr_join_check.one(url) joins and reads the reference materials;
  4. after joining, the footage is checked again: real files -> status joined; only stream links -> status
     joined_no_footage + an alert (never clipped);
  5. config/campaigns_picked.yaml is updated (status, joined date), which the cloud loads into the campaign DB.
Runs on a PC with the HookHouse Chrome (port 9333). Until the coordinator (plan Phase 1-2) routes the job to that
PC, the Control Center/Telegram button calls it through the PC worker; `python cli.py pick join <id>` runs it now."""
from __future__ import annotations

import asyncio
import re
import time

from .config import ROOT

PICKED = ROOT / "config" / "campaigns_picked.yaml"


def _update_picked(cid: str, status: str, note: str) -> None:
    text = PICKED.read_text(encoding="utf-8") if PICKED.exists() else "campaigns:\n"
    block = re.compile(rf"(  - id: {re.escape(cid)}\b[\s\S]*?)(?=\n  - id: |\n  # picked |\Z)")
    m = block.search(text)
    stamp = time.strftime("%Y-%m-%d")
    if m:
        b = m.group(1)
        b = re.sub(r"\n    status: \S+", f"\n    status: {status}", b) if "\n    status:" in b else b + f"\n    status: {status}"
        if "\n    joined:" not in b:
            b += f'\n    joined: "{stamp}"'
        b += f"\n    # {stamp}: {note[:150]}"
        text = text[:m.start(1)] + b + text[m.end(1):]
    else:
        text = text.rstrip() + f'\n  - id: {cid}\n    status: {status}\n    joined: "{stamp}"\n    # {note[:150]}\n'
    PICKED.write_text(text, encoding="utf-8")


def join(cid: str, consent_by: str = "owner", conn=None, runner=None, log=print) -> str:
    from . import db
    from .core import ledger
    from .picker import footage_check
    c = db.get_campaign(conn or db.connect(), cid)
    if not c:
        return f"No campaign {cid!r} in the database."
    fv, fwhy = footage_check(c)
    if fv != "ok":
        return f"🛑 Not joined: footage {fv}: {fwhy}."
    if not c.get("url"):
        return "🛑 Not joined: the campaign has no page link."
    ledger.event("campaign.join_consent", data={"campaign": cid, "by": consent_by, "at": time.time()})
    if runner is None:
        from scripts.cr_join_check import one as runner
    try:
        report = asyncio.run(runner(c["url"]))
    except Exception as e:  # noqa: BLE001 - nothing is recorded as joined when the browser step fails
        ledger.event("campaign.join_failed", data={"campaign": cid, "error": f"{type(e).__name__}: {e}"[:300]})
        return f"⚠️ Join failed ({type(e).__name__}); nothing changed. Is the PC on with the HookHouse Chrome?"
    joined = "joined: True" in report
    clippable = "CLIPPABLE" in report
    if not joined:
        ledger.event("campaign.join_failed", data={"campaign": cid, "report": report[:300]})
        return f"⚠️ The page did not confirm the join: {report[:200]}"
    status = "joined" if clippable or c.get("kick") else "joined_no_footage"
    _update_picked(cid, status, report.splitlines()[0])
    c.update(status=status, joined_at=time.time(), joined_by=consent_by)   # the DB is in the cloud memory bundle
    db.save_campaign(conn or db.connect(), c)
    ledger.event("campaign.joined", data={"campaign": cid, "status": status})
    if status == "joined_no_footage":
        try:
            from .telegram_bot import notify
            notify(f"⚠️ Joined {c.get('name')}, but after joining it shows only stream links: it will not be clipped.")
        except Exception as e:  # noqa: BLE001
            log(f"notify: {e}")
        return f"⚠️ Joined, but no downloadable footage after joining: {report.splitlines()[0]}"
    return f"✅ Joined {c.get('name')}: {report.splitlines()[0]}"


QUEUE = ROOT / "data" / "state" / "join_requests.json"


def request(cid: str, by: str = "owner") -> None:
    """The owner's tap (Telegram Confirm / [Join]) queues a join; the next run with a logged-in browser does it."""
    import json
    from .core import ledger
    try:
        q = json.loads(QUEUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        q = {}
    q[cid] = {"by": by, "at": time.time()}
    from .core.atomic import write_json
    write_json(QUEUE, q)
    ledger.event("campaign.join_requested", data={"campaign": cid, "by": by})


def process_requests(log=print, runner=None) -> int:
    """Run queued joins (cloud tick after the logged-in Chrome is up, or the PC). Each one reports to Telegram."""
    import json
    try:
        q = json.loads(QUEUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not q:
        return 0
    from .core.atomic import write_json
    done = 0
    for cid, info in list(q.items()):
        msg = join(cid, consent_by=info.get("by", "owner"), runner=runner, log=log)
        log(f"join {cid}: {msg}")
        if "Join failed" in msg and time.time() - float(info.get("at") or 0) < 2 * 86400:
            continue                                    # browser trouble: try again next run (for 2 days)
        q.pop(cid, None)
        done += 1
        try:
            from .telegram_bot import notify
            notify(msg)
        except Exception as e:  # noqa: BLE001
            log(f"notify: {e}")
    write_json(QUEUE, q)
    return done
