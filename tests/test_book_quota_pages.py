"""19 Nov: book pages from leftover free cloud picture quota at night (API only, bounded; never the old FLUX farm)."""
from engine import bookart, books_v2
from engine.cloud import book_farm


class FakeStore:
    def __init__(self):
        self.files = {}

    def assets(self, tag):
        return {n: {} for (t, n) in self.files if t == tag}

    def get(self, tag, name):
        return self.files.get((tag, name))

    def put(self, tag, name, data, ctype="x"):
        self.files[(tag, name)] = data
        return {"id": 1}


def test_only_in_the_night_window():
    assert book_farm.quota_pages(FakeStore(), now_mins=12 * 60) == "not book time"


def test_draws_a_few_pages_without_local_flux(tmp_path, monkeypatch):
    monkeypatch.setattr(book_farm, "PROD", tmp_path)
    monkeypatch.setattr(books_v2, "QUEUE", ["christmas_colouring_book"])
    seen = {}

    def maker(pid, log=print, allow_local=True, max_new=None):
        seen.update(allow_local=allow_local, max_new=max_new, skip=bookart.SKIP_CLOUD)
        (tmp_path / pid / "v2").mkdir(parents=True, exist_ok=True)
        (tmp_path / pid / "v2" / "page_09.png").write_bytes(b"png")
        return None                                           # pages still missing

    monkeypatch.setattr(book_farm, "maker_for", lambda pid: maker)
    store = FakeStore()
    out = book_farm.quota_pages(store, per_run=5, now_mins=23 * 60)
    assert seen == {"allow_local": False, "max_new": 5, "skip": False}      # cloud API only, bounded
    assert ("book-christmas_colouring_book", "v2__page_09.png") in store.files
    assert "pages still missing" in out


def test_the_tick_runs_it():
    src = open("engine/cloud/runner.py", encoding="utf-8").read()
    assert '("book_pages"' in src and "quota_pages(store" in src
