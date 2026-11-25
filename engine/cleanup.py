"""Daily disk cleanup (owner, 12 Nov: "if you are using the PC storage then it should be cleaned up daily").

Never touches a video that is still in the pipeline. Keeps:
- every output folder used by a plan item that is planned / made / waiting for approval / approved;
- posted videos for KEEP_POSTED_DAYS after posting (in case a re-upload is needed); after that only the big media
  files go (mp4, wav, work/), the small files stay (upload.json, script, thumbnails) for the learning loop;
- the newest finished video per channel and format (review samples), the latest clip and pitch sample folders.
Removes: temporary work/ folders of finished videos, failed or abandoned renders older than a day, rejected videos
after 2 days, old logs and temp files. Skips everything while a video is being made (render lock).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .config import ROOT

OUT = ROOT / "output"
WEEKS = ROOT / "data" / "weeks"
LOCK = ROOT / "data" / "state" / "render.lock"
KEEP_POSTED_DAYS = 1      # big files of posted videos: 1 day (the platforms have them; disk is tight)
BIG = {".mp4", ".wav", ".mov", ".mkv", ".webm", ".m4a", ".aac", ".flac"}
LIVE = {"planned", "making", "made", "approved", "redo", "needs_source", "failed"}
CACHES = (("cache/images", 14), ("cache/footage", 14), ("cache/scenes", 14), ("cache/posters", 14),
          ("cache/dash_previews", 4), ("test", 7), ("pc/footage", 30))
PC_EVERY_H = 20               # the desktop icon cleans at most this often (the PC no longer runs daily jobs)
PC_STAMP = ROOT / "data" / "state" / "pc_cleanup.txt"


def due_on_pc() -> bool:
    try:
        return time.time() - float(PC_STAMP.read_text(encoding="utf-8")) > PC_EVERY_H * 3600
    except (OSError, ValueError):
        return True


def run_pc(log=print) -> dict:
    """The desktop icon's background clean-up (cloud-only since 18 Nov: nothing else cleans the PC)."""
    res = run(apply=True, log=log)
    PC_STAMP.parent.mkdir(parents=True, exist_ok=True)
    PC_STAMP.write_text(str(time.time()), encoding="utf-8")
    return res


def rendering() -> bool:
    """True while a video is being made (the lock is refreshed by the maker; stale after 6 h)."""
    return LOCK.exists() and time.time() - LOCK.stat().st_mtime < 6 * 3600


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _plan_folders() -> dict[Path, dict]:
    """Output folder -> a summary of the plan items using it. A folder shared by several items (one source, many
    clips) counts as live while ANY of them is live; it counts as posted only when all of them are done."""
    out: dict[Path, dict] = {}
    for plan in sorted(WEEKS.glob("*/plan.json")) if WEEKS.exists() else []:
        try:
            items = json.loads(plan.read_text(encoding="utf-8")).get("items") or []
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            if it.get("out_dir"):
                key = Path(it["out_dir"]).resolve()
                cur = out.get(key)
                st = it.get("status")
                if cur is None:
                    out[key] = {"status": st, "posted_at": it.get("posted_at")}
                elif st in LIVE or cur["status"] in LIVE:
                    cur["status"] = st if st in LIVE else cur["status"]
                elif st == "posted" or cur["status"] == "posted":
                    cur["status"] = "posted"
                    cur["posted_at"] = max(cur.get("posted_at") or 0, it.get("posted_at") or 0) or None
    return out


def _finished(d: Path) -> str | None:
    if (d / "upload.json").exists() and any(d.glob("*.mp4")):
        try:
            return json.loads((d / "upload.json").read_text(encoding="utf-8")).get("format") or "video"
        except Exception:  # noqa: BLE001
            return "video"
    for tag in ("_clips_pitch", "_clips_v3", "_clips"):
        if tag in d.name and any(d.glob("clip_*.mp4")):
            return tag.strip("_")
    if d.parent.name in ("bloop_and_friends", "brain_snack") and any(d.glob("*.mp4")):
        return "sample"
    return None


def plan(now: float | None = None) -> list[tuple[Path, str]]:
    """[(path, reason)] to delete. Paths are whole folders or single big files."""
    now = now or time.time()
    used = _plan_folders()
    try:
        from .weekly import pool_folders
        waiting_clips = pool_folders()                      # clips cut from footage, still waiting for a slot
    except Exception:  # noqa: BLE001
        waiting_clips = set()
    todo: list[tuple[Path, str]] = []
    if not OUT.exists():
        return todo
    for ch in sorted(p for p in OUT.iterdir() if p.is_dir() and p.name != "brand"):
        folders = sorted(p for p in ch.iterdir() if p.is_dir())
        newest: dict[str, Path] = {}
        for d in folders:
            f = _finished(d)
            if f:
                newest[f] = d                                   # sorted by name = time stamp, so last wins
        samples = set(newest.values())
        for d in folders:
            it = used.get(d.resolve())
            age_days = (now - d.stat().st_mtime) / 86400
            if d.resolve() in waiting_clips:
                continue
            if it:
                st = it.get("status")
                if st in LIVE:
                    if st in ("made", "approved") and (d / "work").exists():
                        todo.append((d / "work", "temporary render files of a finished video"))
                    continue
                if st == "posted":
                    posted = it.get("posted_at") or now
                    if (now - posted) / 86400 >= KEEP_POSTED_DAYS:
                        todo += [(f, f"posted {KEEP_POSTED_DAYS}+ days ago (kept its details)")
                                 for f in d.rglob("*") if f.is_file() and f.suffix.lower() in BIG]
                        if (d / "work").exists():
                            todo.append((d / "work", "temporary render files"))
                    continue
                if st in ("rejected", "missed") and age_days >= 2:
                    todo.append((d, f"{st} video, 2+ days old"))
                    continue
                continue
            if d in samples:
                if (d / "work").exists():
                    todo.append((d / "work", "temporary render files of a sample"))
                continue
            if age_days >= 1:
                todo.append((d, "old render not used by any plan" if _finished(d) else "failed or unfinished render"))
    for p in (ROOT / "data").glob("tmp_*"):
        todo.append((p, "temporary file"))
    # 19 Nov (owner: "the folder got bigger and bigger, >24 GB"): download caches and test renders are rebuilt on
    # demand, so old ones go too
    for sub, days in CACHES:
        base = ROOT / "data" / sub
        for f in base.rglob("*") if base.exists() else []:
            if f.is_file() and (now - f.stat().st_mtime) / 86400 > days:
                todo.append((f, f"{sub} older than {days} days"))
    prev = ROOT / "data" / "telegram" / "previews"
    for f in prev.glob("*.mp4") if prev.exists() else []:
        if (now - f.stat().st_mtime) / 86400 > 3:
            todo.append((f, "phone preview older than 3 days"))
    for log in list((ROOT / "data").rglob("*.log")):
        # 25 Nov: this also matched Chrome's own LevelDB write-ahead logs inside data/browser_profile (Local Storage,
        # IndexedDB: the saved logins' site data) and deleted the old ones; a file Chrome removed mid-scan crashed it
        if any("profile" in part.lower() for part in log.relative_to(ROOT / "data").parts[:-1]):
            continue
        try:
            if (now - log.stat().st_mtime) / 86400 > 14:
                todo.append((log, "log older than 14 days"))
        except FileNotFoundError:
            continue
    return [(p, why) for p, why in todo if p.exists()]


def run(apply: bool = True, log=print) -> dict:
    if rendering():
        log("Cleanup skipped: a video is being made right now.")
        return {"skipped": True, "freed_gb": 0.0, "items": 0}
    items = plan()
    total = sum(_size(p) for p, _ in items)
    if apply:
        for p, _ in items:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    free = shutil.disk_usage(ROOT).free / 1e9
    log(f"Cleanup {'done' if apply else '(dry run)'}: {len(items)} items, {total / 1e9:.2f} GB"
        f"{' freed' if apply else ' would be freed'}; {free:.1f} GB free")
    return {"skipped": False, "freed_gb": round(total / 1e9, 2), "items": len(items), "free_gb": round(free, 1),
            "list": [(str(p.relative_to(ROOT)), why) for p, why in items]}
