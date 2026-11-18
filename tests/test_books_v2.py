"""Books v2 (owner, 17 Nov 2026): AI line art cleaned into print art, checked pages, learning-book layouts."""
import numpy as np
from PIL import Image, ImageDraw

from engine import bookart, books_v2


def drawing(seed=0, shapes=6):
    """A fake 'AI drawing': grey background, a few outlined shapes (like a cartoon)."""
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (640, 832), (235, 235, 235))
    d = ImageDraw.Draw(im)
    for _ in range(shapes):
        x, y = rng.integers(60, 460), rng.integers(60, 600)
        r = int(rng.integers(50, 140))
        d.ellipse((x, y, x + r, y + r), outline=(10, 10, 10), width=4)
    return im


def test_clean_makes_pure_black_white_thick_lines():
    art = bookart.clean(drawing(), page_px=(1125, 1425), stroke=9)
    a = np.asarray(art)
    assert set(np.unique(a)) <= {0, 255}
    assert art.size == (1125, 1425)
    s = bookart.stats(art)
    assert 0.01 < s["ink"] < 0.4 and s["regions"] >= 3


def test_qa_flags_blobs_and_empty_pages():
    blank = Image.new("L", (1125, 1425), 255)
    assert any("ink" in p for p in bookart.qa(blank, "kids"))
    blob = blank.copy()
    ImageDraw.Draw(blob).rectangle((200, 200, 900, 900), fill=0)
    assert any("black area" in p for p in bookart.qa(blob, "kids"))


def test_near_duplicates_are_caught():
    a = bookart.clean(drawing(1), page_px=(900, 1100))
    b = bookart.clean(drawing(2, shapes=9), page_px=(900, 1100))
    assert bookart.near(bookart.dhash(a), bookart.dhash(a))
    assert not bookart.near(bookart.dhash(a), bookart.dhash(b))


def test_page_redraws_until_clean(monkeypatch):
    calls = []

    def fake_draw(prompt, seed, prefer_cloud=True, size=(640, 832), allow_local=True):
        calls.append(seed)
        return (Image.new("RGB", (640, 832), "white") if len(calls) == 1 else drawing(seed)), "test"
    monkeypatch.setattr(bookart, "draw", fake_draw)
    pg = bookart.page("a cat", age="toddler", seed=5, used=[], log=lambda *_: None)
    assert pg is not None and len(calls) == 2


def test_no_quota_and_no_local_raises(monkeypatch):
    monkeypatch.setattr(bookart, "draw_cloud", lambda p, s, size=None: (None, ""))
    monkeypatch.setattr(bookart, "CACHE", bookart.CACHE.parent / "tmp_bookart_test")
    try:
        bookart.draw("x", 1, allow_local=False)
        raised = False
    except bookart.NoPicture:
        raised = True
    assert raised


def test_learning_pages_render():
    from engine.book_specs import USA
    from engine.config import ROOT
    # the Census map files live in data/geo on the PC (books are a PC job); the cloud test run has no data/
    if (ROOT / "data" / "geo" / "us_states" / "cb_2023_us_state_20m.shp").exists():
        p = books_v2.state_page("Texas", USA["Texas"], None)
        assert p.size == (books_v2.PW, books_v2.PH) and np.asarray(p).min() == 0
    pages = books_v2.alphabet_pages("B", "Bear", None)
    assert len(pages) == 4                                  # letter page, blank back, tracing page, blank back
    assert books_v2.certificate_page("X").size == (books_v2.PW, books_v2.PH)


def test_color_by_number_numbers_and_answer():
    art = bookart.clean(drawing(3), page_px=(2250, 2500), stroke=14)
    page, ans = books_v2.color_by_number(art)
    assert page.size == (books_v2.PW, books_v2.PH) and ans.mode == "RGB"
    assert len(np.unique(np.asarray(ans).reshape(-1, 3), axis=0)) > 3     # areas got colours


def test_cloud_falls_back_to_hugging_face_within_the_daily_cap(tmp_path, monkeypatch):
    import io
    from engine import storyboard
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    monkeypatch.setattr(bookart, "HF_COUNT", tmp_path / "hf.json")
    monkeypatch.setattr(storyboard, "_cloudflare", lambda *a, **k: None)          # Cloudflare quota used up
    calls = []
    monkeypatch.setattr(storyboard, "_hf", lambda p, s, size: calls.append(s) or buf.getvalue())
    monkeypatch.setattr(bookart, "HF_BOOK_MAX", 2)
    assert bookart.draw_cloud("x", 1)[1] == "hf" and bookart.draw_cloud("x", 2)[1] == "hf"
    assert bookart.draw_cloud("x", 3) == (None, "") and len(calls) == 2          # cap reached: videos keep the rest
