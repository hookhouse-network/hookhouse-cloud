"""Draw the first N pages of a book with the PC's own FLUX (same prompt/seed as books_v2.build, so they are cached
and reused by the real build). Usage: python -m scripts.book_test_pages <book_id> [n]"""
import sys
import time

from engine import bookart, books_v2
from engine.book_specs import BOOKS

pid = sys.argv[1] if len(sys.argv) > 1 else "christmas_colouring_book"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
spec = BOOKS[pid]
out = books_v2.PROD / pid / "v2"
out.mkdir(parents=True, exist_ok=True)
bookart.SKIP_CLOUD = True
used: list[int] = []
for k, subj in enumerate(spec["subjects"][:n]):
    t = time.time()
    pg = bookart.page(subj, age=spec["age"], seed=spec["seed"] + k * 31, used=used, prefer_cloud=False,
                      page_px=books_v2.ART, tries=1, log=lambda m: print(m, flush=True))
    if pg:
        pg.image.save(out / f"page_{k + 1:02d}.png")
    print(f"page {k + 1} '{subj[:50]}': {'ok ' + str(pg.stats) if pg else 'failed checks'} "
          f"({(time.time() - t) / 60:.1f} min)", flush=True)
