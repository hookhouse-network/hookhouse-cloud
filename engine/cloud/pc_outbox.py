"""PC upload outbox + disk guard (master plan Phase 0, items 4b and 4c; 20 Nov 2026).

4b. The PC maker log showed SSLError / ConnectionError to uploads.github.com. Before this, a failed upload went to the
helper's generic error handler: the finished video was forgotten, the claim expired after CLAIM_H, and the video was
made again. Now a finished video becomes a pending record FIRST (data/pc/pending_uploads/<item>.json, atomic write),
then uploads are tried with capped exponential backoff + jitter until they work. Each try refreshes the claim
("uploading") so the cloud never gives the slot to someone else. Pending records survive restarts. After
REPORT_AFTER failures an alert rides on the PC heartbeat, and the cloud watchdog tells the owner (the PC never
messages anyone itself).

4c. D: had 16 GB free. Before claiming new work: below MIN_FREE_GB run cleanup.run_pc; still low -> claim nothing,
raise the alert, try again next loop. Uploads of finished videos keep going (they free space)."""
from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path

from ..config import ROOT

PENDING = ROOT / "data" / "pc" / "pending_uploads"
REPORT_AFTER = 5
BASE_S = 60.0
MAX_WAIT_S = 1800.0
MIN_FREE_GB = 5.0
_disk_alert: dict[str, str] = {}


def _write(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)                                   # atomic on the same disk: never a half-written record


def add(item_id: str, folder: Path, marker: dict, now: float | None = None) -> Path:
    """A finished video waits here until its upload and done marker are in cloud storage."""
    path = PENDING / f"{item_id}.json"
    _write(path, {"id": item_id, "folder": str(folder), "marker": marker, "attempts": 0, "next_at": 0.0,
                  "added": now or time.time(), "error": ""})
    return path


def pending() -> list[dict]:
    out = []
    for p in sorted(PENDING.glob("*.json")) if PENDING.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"pending upload record unreadable: {p.name}: {e}")
    return out


def backoff(attempts: int, rnd: float | None = None) -> float:
    """60 s, 120 s, 240 s ... capped at 30 min, times a jitter of 0.5-1.5 (many PCs never retry in step)."""
    base = min(MAX_WAIT_S, BASE_S * 2 ** max(0, attempts - 1))
    return base * (0.5 + (random.random() if rnd is None else rnd))


def flush(store, log=print, now: float | None = None) -> int:
    """Try every pending upload that is due. Returns how many reached the cloud."""
    from . import media
    now = now or time.time()
    done = 0
    for rec in pending():
        if float(rec.get("next_at") or 0) > now:
            continue
        path = PENDING / f"{rec['id']}.json"
        folder = Path(rec["folder"])
        if not folder.exists() or not any(folder.glob("*.mp4")):
            log(f"upload {rec['id']}: the finished folder is gone ({folder}); the cloud remakes this slot")
            path.unlink(missing_ok=True)
            continue
        try:
            store.put(media.TAG, f"claim-{rec['id']}.json",              # keep the slot ours while we retry
                      json.dumps({"id": rec["id"], "at": now, "state": "uploading"}).encode())
            media.upload(store, rec["id"], folder)
            store.put(media.TAG, f"done-{rec['id']}.json", json.dumps(rec["marker"], ensure_ascii=False).encode())
        except Exception as e:  # noqa: BLE001 - keep the file, try again later
            rec["attempts"] = int(rec.get("attempts") or 0) + 1
            wait = backoff(rec["attempts"])
            rec["next_at"], rec["error"] = now + wait, f"{type(e).__name__}: {str(e)[:200]}"
            _write(path, rec)
            log(f"upload {rec['id']} failed ({rec['attempts']}x, next try in {wait / 60:.0f} min): {rec['error']}")
            continue
        path.unlink(missing_ok=True)
        _remember_upload(rec["id"], float((rec.get("marker") or {}).get("made_at") or 0), now)
        done += 1
        log(f"uploaded {rec['id']}" + (f" after {rec['attempts']} failed tries" if rec.get("attempts") else ""))
    return done


# 22 Nov 09:26: the PC made the Itihaas 12:30 video AGAIN three minutes after uploading it. The cloud tick that merged
# it had already deleted its claim, but saves the plan only at its end, so the PC's fresh copy still showed the video
# unmade and unclaimed (35 min and ~11 local pictures wasted). The PC now remembers what it uploaded and skips a video
# until its plan copy shows the merged make (made_at equal to ours: then a 'redo' there is a real remake request).
UPLOADED = ROOT / "data" / "pc" / "uploaded.json"
UPLOAD_TRUST_H = 6            # a merge that never shows up in the copy for this long: the PC may make it again


def _uploads() -> dict:
    try:
        d = json.loads(UPLOADED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cut = time.time() - 2 * 86400
    return {k: v for k, v in d.items() if isinstance(v, dict) and float(v.get("uploaded") or 0) > cut}


def _remember_upload(item_id: str, made_at: float, now: float) -> None:
    d = _uploads()
    d[item_id] = {"made_at": made_at, "uploaded": now}
    UPLOADED.parent.mkdir(parents=True, exist_ok=True)
    UPLOADED.write_text(json.dumps(d, indent=1), encoding="utf-8")


def awaiting_merge(it: dict, now: float | None = None) -> bool:
    """True when this PC uploaded the video and its plan copy does not show that make yet (a stale copy)."""
    rec = _uploads().get(it.get("id"))
    if not rec:
        return False
    now = now or time.time()
    if now - float(rec.get("uploaded") or 0) > UPLOAD_TRUST_H * 3600:
        return False
    return float(it.get("made_at") or 0) < float(rec.get("made_at") or 0) - 1


def disk_ok(log=print, path: Path | None = None, cleanup=None) -> bool:
    """True when there is room to claim new work. Below MIN_FREE_GB: clean up once, check again."""
    path = path or ROOT
    free = shutil.disk_usage(path).free / 1e9
    if free >= MIN_FREE_GB:
        _disk_alert.clear()
        return True
    log(f"disk: only {free:.1f} GB free (need {MIN_FREE_GB:.0f} GB): cleaning up before new work")
    try:
        if cleanup is None:
            from ..cleanup import run_pc as cleanup
        cleanup(log=log)
    except Exception as e:  # noqa: BLE001 - still report the low disk below
        log(f"disk clean-up failed: {type(e).__name__}: {e}")
    free = shutil.disk_usage(path).free / 1e9
    if free >= MIN_FREE_GB:
        _disk_alert.clear()
        log(f"disk: {free:.1f} GB free after clean-up")
        return True
    _disk_alert["disk"] = (f"The PC disk has only {free:.1f} GB free, so the PC stopped taking new videos (it needs "
                           f"{MIN_FREE_GB:.0f} GB). Fix: delete big files you don't need on the PC's D: drive; it "
                           "starts again by itself.")
    log("disk: still low after clean-up; not taking new videos")
    return False


def alerts() -> dict[str, str]:
    """Plain-words alerts for the PC heartbeat (the cloud watchdog sends them to the owner)."""
    out = dict(_disk_alert)
    for rec in pending():
        if int(rec.get("attempts") or 0) >= REPORT_AFTER:
            out[f"upload:{rec['id']}"] = (
                f"A finished video ({rec['id']}) could not be uploaded from the PC {rec['attempts']} times "
                f"({rec.get('error', '')[:120]}). It is kept and retried every 30 min; nothing is lost. If this "
                "stays, check the PC's internet.")
    return out
