"""P9 disaster-recovery drill (27 Nov): can the cloud memory really be restored? Downloads the current bundle and
its backup (engine/cloud/state.py keeps the previous save as BACKUP), unpacks each into a throwaway folder and checks
that it is usable: every weekly plan parses, the ledger database opens and answers, the publish log parses. Reports
what a restore from the backup would lose. Read-only: nothing is written back.
python -m engine.cloud.dr_drill"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path


def check_tree(root: Path) -> dict:
    """{plans, plan_errors, items, ledger_events, ledger_ok, log_lines, log_bad}"""
    out = {"plans": 0, "plan_errors": [], "items": 0, "ledger_events": 0, "ledger_ok": False, "log_lines": 0,
           "log_bad": 0}
    for p in sorted((root / "data" / "weeks").glob("*/plan.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out["plans"] += 1
            out["items"] += len(d.get("items") or [])
        except (OSError, ValueError) as e:
            out["plan_errors"].append(f"{p.parent.name}: {type(e).__name__}")
    db = root / "data" / "ledger.db"
    if db.exists():
        try:
            c = sqlite3.connect(str(db))
            out["ledger_events"] = c.execute("SELECT count(*) FROM events").fetchone()[0]
            out["ledger_ok"] = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            c.close()
        except sqlite3.Error as e:
            out["plan_errors"].append(f"ledger: {type(e).__name__}: {e}")
    log = root / "data" / "publish_log.jsonl"
    if log.exists():
        for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
            out["log_lines"] += 1
            try:
                json.loads(ln)
            except ValueError:
                out["log_bad"] += 1
    return out


def usable(r: dict) -> bool:
    return r["plans"] > 0 and not r["plan_errors"] and r["ledger_ok"] and r["log_lines"] > 0


def drill(store=None, log=print) -> dict:
    from . import state
    from .store import Store
    store = store or Store()
    report = {}
    for label, name in (("current", state.NAME), ("backup", state.BACKUP)):
        blob = store.get(state.TAG, name)
        if not blob:
            report[label] = {"missing": True}
            log(f"DR drill: {label}: no bundle stored")
            continue
        with tempfile.TemporaryDirectory(prefix=f"hh_dr_{label}_") as tmp:
            n = state.unpack(blob, Path(tmp))
            r = check_tree(Path(tmp))
            r.update(files=n, size_kb=len(blob) // 1024, usable=usable(r))
            report[label] = r
            log(f"DR drill: {label}: {n} files, {r['plans']} plans / {r['items']} items, ledger "
                f"{'ok' if r['ledger_ok'] else 'BAD'} ({r['ledger_events']} events), publish log {r['log_lines']} lines "
                f"({r['log_bad']} unreadable) -> {'USABLE' if r['usable'] else 'NOT usable'}")
    cur, bak = report.get("current") or {}, report.get("backup") or {}
    if cur.get("usable") and bak.get("usable"):
        report["restore_loses"] = {"items": cur["items"] - bak["items"], "events": cur["ledger_events"] -
                                   bak["ledger_events"], "log_lines": cur["log_lines"] - bak["log_lines"]}
        log(f"DR drill: restoring the backup would lose {report['restore_loses']}")
    return report


if __name__ == "__main__":
    from ..config import load_env
    load_env()
    drill()
