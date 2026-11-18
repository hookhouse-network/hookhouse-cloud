"""Finished video folders travel between the cloud and the PC as zip files in the private repo (release "videos")."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from ..config import ROOT

TAG = "videos"
SKIP_DIRS = {"work", "__pycache__"}


def rel_out(path: str | Path) -> str:
    """'D:\\clipping-system\\output\\x\\y' or '/home/runner/.../output/x/y' -> 'output/x/y' (works on both)."""
    s = str(path).replace("\\", "/").rstrip("/")
    i = s.find("/output/")
    if i >= 0:
        return s[i + 1:]
    if s.startswith("output/"):
        return s
    return "output/" + s.split("/")[-1]


def local_dir(path: str | Path) -> Path:
    return ROOT / rel_out(path)


def zip_dir(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:           # videos are already compressed
        for f in sorted(folder.rglob("*")):
            if f.is_file() and not (set(f.relative_to(folder).parts[:-1]) & SKIP_DIRS):
                z.write(f, f.relative_to(folder).as_posix())
    return buf.getvalue()


def unzip_to(blob: bytes, folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for m in z.infolist():
            if m.is_dir() or m.filename.startswith("/") or ".." in Path(m.filename).parts:
                continue
            dest = folder / m.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(m))
            n += 1
    return n


def asset_name(item_id: str) -> str:
    return f"{item_id}.zip"


def upload(store, item_id: str, folder: Path) -> str:
    name = asset_name(item_id)
    store.put(TAG, name, zip_dir(folder), "application/zip")
    return name


def ensure_local(store, it: dict) -> Path | None:
    """The item's folder on this machine (downloaded from the repo if it isn't here yet)."""
    if not it.get("out_dir"):
        return None
    folder = local_dir(it["out_dir"])
    if folder.exists() and any(folder.glob("*.mp4")):
        return folder
    name = it.get("cloud_asset") or asset_name(it["id"])
    blob = store.get(TAG, name)
    if not blob:
        return None
    unzip_to(blob, folder)
    return folder
