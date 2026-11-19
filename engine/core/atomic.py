"""Crash-safe file writes. `Path.write_text` truncates the file first, so a crash, a full disk or a killed run in the
middle leaves half a JSON file, and the next reader silently treats it as empty (lost tokens, lost decisions). Here
the data goes to a temporary file in the same folder, is flushed to disk, then replaces the old file in one step
(os.replace is atomic on Windows and Linux): readers see the old version or the new one, never a broken one."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_text(path: Path | str, text: str, encoding: str = "utf-8") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def write_json(path: Path | str, data, indent: int | None = 1) -> Path:
    return write_text(path, json.dumps(data, indent=indent, ensure_ascii=False, default=str))
