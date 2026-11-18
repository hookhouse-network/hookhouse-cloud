"""The system's memory as one small encrypted bundle (databases, weekly plans, logins, campaign records, the owner's
to-do ticks). Every cloud job pulls it first and pushes it back last; GitHub runs these jobs one at a time
(concurrency group "state"), so nothing is lost. Encrypted with STATE_KEY (a Fernet key kept only in the repo's
Actions secrets and the PC's .env), so even the private repo never holds a readable login."""
from __future__ import annotations

import io
import os
import tarfile
import time
from pathlib import Path

from ..config import ROOT

TAG = "state"
NAME = "state.bin"
BACKUP = "state.prev.bin"
PATHS = ["data/system.db", "data/analytics.db", "data/memory.db", "data/publish_log.jsonl", "data/snack_history.json",
         "data/snack_league.json", "data/state", "data/weeks", "data/pitches", "data/campaigns", "data/campaign_proof",
         "data/permissions", "data/secrets", "data/telegram", "data/templates", "data/reviews",
         "config/owner_todo.yaml", "config/clip_sources.yaml",
         # 18 Nov: campaign footage (joined campaigns) + /source links live here. It was missing from the bundle, so
         # every cloud run forgot them and Hot Take HQ said "No clip footage left": no campaign clip was ever made.
         "data/clip_sources.txt"]
SKIP = {"render.lock", "heartbeat.txt"}
SKIP_EXT = {".mp4", ".mov", ".webm", ".wav", ".mp3"}    # media lives in the video store; a 43 MB Telegram preview
                                                        # once made the memory bundle 58 MB (15 Nov)
MAX_FILE = 50 * 1024 * 1024                      # nothing big belongs in the memory bundle


def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("STATE_KEY", "").strip()
    if not key:
        raise RuntimeError("STATE_KEY is not set")
    return Fernet(key.encode())


def new_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def pack(root: Path = ROOT) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in PATHS:
            p = root / rel
            if not p.exists():
                continue
            files = [p] if p.is_file() else [f for f in sorted(p.rglob("*")) if f.is_file()]
            for f in files:
                if f.name in SKIP or f.suffix.lower() in SKIP_EXT or f.stat().st_size > MAX_FILE:
                    continue
                tar.add(f, arcname=f.relative_to(root).as_posix())
    return _fernet().encrypt(buf.getvalue())


def unpack(blob: bytes, root: Path = ROOT) -> int:
    raw = _fernet().decrypt(blob)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = m.name
            if not m.isfile() or name.startswith("/") or ".." in Path(name).parts or ":" in name:
                continue                                   # never write outside the project folder
            if not any(name == r or name.startswith(r + "/") for r in PATHS):
                continue
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tar.extractfile(m).read())
            n += 1
    return n


def pull(store, root: Path = ROOT) -> int:
    """Download and unpack the memory bundle. 0 = first run (nothing stored yet)."""
    blob = store.get(TAG, NAME)
    return unpack(blob, root) if blob else 0


def push(store, root: Path = ROOT) -> int:
    """Pack and upload; the previous bundle is kept as a backup first."""
    blob = pack(root)
    try:                                            # the backup copy is a nice-to-have: a slow GitHub download of it
        old = store.get(TAG, NAME)                  # once lost a finished video's "made" status (15 Nov)
        if old:
            store.put(TAG, BACKUP, old)
    except Exception:  # noqa: BLE001
        pass
    for attempt in range(3):                        # the real save: retry a timeout / blip
        try:
            store.put(TAG, NAME, blob)
            break
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    (root / "data" / "state").mkdir(parents=True, exist_ok=True)
    (root / "data" / "state" / "cloud_pushed.txt").write_text(str(time.time()), encoding="utf-8")
    return len(blob)
