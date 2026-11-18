"""Book picture farm in the cloud (owner 18 Nov 2026: "all the processes should be done on cloude", "use in house image
generators"). Replaces the PC's night worker.

Each farm machine (.github/workflows/pictures.yml, matrix shard i of n) runs our own FLUX.1-schnell (Apache 2.0) with
stable-diffusion.cpp (MIT) and takes a DIFFERENT unfinished book: shard i -> the i-th unfinished book of
books_v2.QUEUE, so two machines never draw the same page. The book's files live in the private store, release tag
"book-<id>": a machine first pulls what exists (pages drawn by earlier runs), then draws, and uploads every new page at
once (a 6-hour job limit never loses work). When the book has all its pages, the same builder makes the PDF + covers,
uploads them and sends the book to the owner on Telegram for review (nothing goes to Amazon/Payhip without ✅).
"""
from __future__ import annotations

import time
from pathlib import Path

from ..config import ROOT

PROD = ROOT / "data" / "products"
SEP = "__"                                     # a sub-folder in an asset name: v2__page_01.png <-> v2/page_01.png
KEEP = (".png", ".jpg", ".pdf", ".json")


def tag(pid: str) -> str:
    return f"book-{pid}"


def _local_files(pid: str) -> dict[str, Path]:
    """name in the store -> local file, for everything the builders write for this book."""
    root = PROD / pid
    if not root.exists():
        return {}
    out = {}
    for f in root.rglob("*"):
        if f.is_file() and f.suffix.lower() in KEEP and ("v2" in f.parts or "_v2" in f.name):
            out[SEP.join(f.relative_to(root).parts)] = f
    return out


def pull(store, pid: str) -> int:
    """Download the book's stored files that are not here yet."""
    have = _local_files(pid)
    n = 0
    for name, a in store.assets(tag(pid)).items():
        if name in have:
            continue
        data = store.get(tag(pid), name)
        if data is None:
            continue
        dest = PROD / pid / Path(*name.split(SEP))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        n += 1
    return n


def push(store, pid: str, known: set[str]) -> int:
    """Upload files written since `known` (names) was taken; adds them to `known`."""
    n = 0
    for name, f in _local_files(pid).items():
        if name in known:
            continue
        ctype = {".png": "image/png", ".jpg": "image/jpeg", ".pdf": "application/pdf"}.get(f.suffix.lower(),
                                                                                        "application/json")
        store.put(tag(pid), name, f.read_bytes(), ctype)
        known.add(name)
        n += 1
    return n


def done(store, pid: str) -> bool:
    return "kdp_listing_v2.json" in store.assets(tag(pid))


def unfinished(store) -> list[str]:
    from ..books_v2 import QUEUE
    return [pid for pid in QUEUE if not done(store, pid)]


def maker_for(pid: str):
    from .. import books_v2
    from ..book_specs import BOOKS
    kind = BOOKS[pid]["kind"]
    if kind == "activity":
        from ..activity_v2 import build_activity
        return build_activity
    if kind == "tracing":
        from ..activity_v2 import build_tracing
        return build_tracing
    if kind == "seniors_ws":
        from ..activity_v2 import build_seniors
        return build_seniors
    if kind in ("alphabet", "states", "world", "india", "numbers"):
        return books_v2.build_learning
    return books_v2.build_cbn if kind == "cbn" else books_v2.build


def work(store, shard: int = 0, shards: int = 1, minutes: float = 330, log=print) -> str:
    """One farm machine: draw pages of book number `shard` among the unfinished ones until it is complete or the time
    is up. In-house pictures only (bookart.SKIP_CLOUD: no third-party quota)."""
    from .. import bookart, books_v2
    todo = unfinished(store)
    if shard >= len(todo):
        return "no book for this machine"
    pid = todo[shard]
    if pid == "tracing_workbook":                  # draws nothing: needs the alphabet + counting books' pictures
        for dep in ("fun_alphabet", "numbers_counting"):
            pull(store, dep)
    pull(store, pid)
    known = set(_local_files(pid))
    maker = maker_for(pid)
    t0, idle = time.time(), 0
    bookart.SKIP_CLOUD = True
    try:
        while (time.time() - t0) / 60 < minutes:
            res = maker(pid, log=log, allow_local=True, max_new=1)
            if push(store, pid, known):            # every new page is safe at once
                idle = 0
            elif res is None:
                idle += 1
                if idle >= 3:                      # nothing new three times: drawing is broken or the book waits
                    return f"{pid}: stopped, no new page in 3 tries (see the log above)"
            if res is not None:
                log(f"{pid}: complete")
                try:
                    books_v2._send_book(pid, res, log)
                except Exception as e:  # noqa: BLE001 - the files are stored either way
                    log(f"{pid}: telegram: {e}")
                return f"{pid}: built"
        return f"{pid}: pages in progress (time up)"
    finally:
        bookart.SKIP_CLOUD = False
        push(store, pid, known)
