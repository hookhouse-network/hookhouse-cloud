"""18 Nov: book pictures drawn by the in-house cloud farm (no PC): one book per machine, every page stored at once."""
from engine.cloud import book_farm


class FakeStore:
    def __init__(self):
        self.files: dict[str, dict[str, bytes]] = {}

    def assets(self, tag):
        return {n: {} for n in self.files.get(tag, {})}

    def get(self, tag, name):
        return self.files.get(tag, {}).get(name)

    def put(self, tag, name, data, content_type="application/octet-stream"):
        self.files.setdefault(tag, {})[name] = data
        return {}


def test_pages_round_trip_through_the_store(tmp_path, monkeypatch):
    monkeypatch.setattr(book_farm, "PROD", tmp_path)
    (tmp_path / "bk" / "v2").mkdir(parents=True)
    (tmp_path / "bk" / "v2" / "page_01.png").write_bytes(b"p1")
    (tmp_path / "bk" / "notes.txt").write_text("not a book file")
    st = FakeStore()
    known: set[str] = set()
    assert book_farm.push(st, "bk", known) == 1 and set(st.files["book-bk"]) == {"v2__page_01.png"}
    assert book_farm.push(st, "bk", known) == 0                             # nothing twice
    other = tmp_path / "other"
    monkeypatch.setattr(book_farm, "PROD", other)                           # another machine
    assert book_farm.pull(st, "bk") == 1 and (other / "bk" / "v2" / "page_01.png").read_bytes() == b"p1"


def test_each_machine_takes_a_different_book_and_stops_when_drawing_fails(tmp_path, monkeypatch):
    from engine import books_v2
    monkeypatch.setattr(book_farm, "PROD", tmp_path)
    monkeypatch.setattr(books_v2, "QUEUE", ["a", "b", "c"])
    st = FakeStore()
    st.files["book-a"] = {"kdp_listing_v2.json": b"{}"}                     # a is finished
    assert book_farm.unfinished(st) == ["b", "c"]
    drawn = []

    def maker(pid, log=print, allow_local=True, max_new=None):
        drawn.append(pid)
        return None                                                         # never draws anything
    monkeypatch.setattr(book_farm, "maker_for", lambda pid: maker)
    msg = book_farm.work(st, shard=1, shards=2, minutes=5, log=lambda *_: None)
    assert set(drawn) == {"c"} and len(drawn) == 3 and "stopped" in msg
    assert book_farm.work(st, shard=5, shards=8, log=lambda *_: None) == "no book for this machine"


def test_a_finished_book_is_sent_for_review(tmp_path, monkeypatch):
    from engine import books_v2
    monkeypatch.setattr(book_farm, "PROD", tmp_path)
    monkeypatch.setattr(books_v2, "QUEUE", ["bk"])
    sent = []
    monkeypatch.setattr(books_v2, "_send_book", lambda pid, res, log=print: sent.append(pid))
    calls = []

    def maker(pid, log=print, allow_local=True, max_new=None):
        calls.append(1)
        page = tmp_path / pid / "v2" / f"page_{len(calls):02d}.png"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_bytes(b"x")
        if len(calls) == 3:
            (tmp_path / pid / "kdp_listing_v2.json").write_text("{}")
            return {"title": "T", "pages": 3}
        return None
    monkeypatch.setattr(book_farm, "maker_for", lambda pid: maker)
    st = FakeStore()
    assert book_farm.work(st, log=lambda *_: None) == "bk: built" and sent == ["bk"]
    assert book_farm.done(st, "bk") and len(st.files["book-bk"]) == 4


def test_brand_jobs_bios_and_layouts(tmp_path):
    from PIL import Image
    from engine import brand_art
    from engine.config import channels
    ids = {c["id"] for c in channels()}
    assert set(brand_art.ART) <= ids and set(brand_art.BIOS) == set(brand_art.ART)
    for ig, fb in brand_art.BIOS.values():
        assert len(ig) <= 150 and len(fb) <= 101
    assert len(brand_art.jobs()) == 2 * len(brand_art.ART)
    files = brand_art.compose("deep_blue_files", Image.new("RGB", (768, 768), "teal"),
                              Image.new("RGB", (1344, 768), "navy"), out=tmp_path)
    sizes = {k: Image.open(v).size for k, v in files.items()}
    assert sizes == {"avatar.png": (1080, 1080), "youtube_banner.jpg": (2560, 1440), "facebook_cover.jpg": (1640, 624)}
