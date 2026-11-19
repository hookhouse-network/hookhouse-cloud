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
PATHS = ["data/system.db", "data/analytics.db", "data/memory.db", "data/ledger.db", "data/publish_log.jsonl", "data/snack_history.json",
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


# ---------- secrets inbox (18 Nov: the PC never pushes the whole bundle; a new login made in a coding session is
# dropped here encrypted and merged by the next cloud run, so nothing races with a running job) ----------
INBOX = "secrets-inbox.bin"
SECRETS_DIR = "data/secrets"


def send_secrets(store, names: list[str], root: Path = ROOT) -> int:
    """PC: put these data/secrets/<name> files (and nothing else) into the cloud's inbox, encrypted."""
    import json
    files = {}
    for n in names:
        p = root / SECRETS_DIR / n
        if p.is_file() and "/" not in n and "\\" not in n and ".." not in n:
            files[n] = p.read_text(encoding="utf-8")
    if not files:
        return 0
    old = store.get(TAG, INBOX)
    if old:                                          # an earlier drop not merged yet: keep both
        files = {**json.loads(_fernet().decrypt(old)), **files}
    store.put(TAG, INBOX, _fernet().encrypt(json.dumps(files).encode()))
    return len(files)


def merge_secrets(store, root: Path = ROOT, log=print) -> int:
    """Cloud (right after pull): write the inbox's login files into data/secrets, then empty the inbox."""
    import json
    blob = store.get(TAG, INBOX)
    if not blob:
        return 0
    files = json.loads(_fernet().decrypt(blob))
    d = root / SECRETS_DIR
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, text in files.items():
        if "/" in name or "\\" in name or ".." in name:
            continue
        (d / name).write_text(text, encoding="utf-8")
        n += 1
    store.delete(TAG, INBOX)
    log(f"logins from the PC merged: {n} file(s)")
    return n
