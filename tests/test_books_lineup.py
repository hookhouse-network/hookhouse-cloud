"""Books line-up of 18 Nov 2026 (owner: cute, funny, educational, trendy, not only Bloop)."""
import numpy as np
from PIL import Image, ImageDraw

from engine import books_v2
from engine.book_specs import BOOKS, NUMBERS


def _blob(size=(400, 400)):
    im = Image.new("L", size, 255)
    ImageDraw.Draw(im).ellipse((40, 40, size[0] - 40, size[1] - 40), fill=0)
    return im


def test_every_queued_book_has_a_spec_and_enough_designs():
    for pid in books_v2.QUEUE:
        spec = BOOKS[pid]
        assert spec["age_label"] and spec["title"] and spec["price"] > 0
        if spec["kind"] == "colouring":
            subs = [s[0] if isinstance(s, tuple) else s for s in spec["subjects"]]
            assert len(subs) >= 30 and len(set(subs)) == len(subs), pid          # no repeated pictures


def test_no_famous_cartoon_characters_in_any_book():
    banned = ("mickey", "peppa", "bluey", "pokemon", "pikachu", "elsa", "spongebob", "paw patrol", "cocomelon",
              "barbie", "sonic", "mario", "minion", "hello kitty", "dora")
    for pid, spec in BOOKS.items():
        text = " ".join(str(s) for s in spec.get("subjects", [])) + spec["title"] + spec["subtitle"]
        assert not any(b in text.lower() for b in banned), pid


def test_fun_facts_fit_on_two_lines():
    d = ImageDraw.Draw(Image.new("L", (10, 10)))
    f = books_v2.font(68, "Poppins-ExtraBold.ttf")
    for pid in ("ocean_animals", "space_adventure", "nature_walk"):
        for _, fact in BOOKS[pid]["subjects"]:
            assert len(books_v2._wrap(f"Fun fact: {fact}", f, books_v2.PW - 400, d)) <= 2, fact


def test_counting_page_shows_exactly_n_pictures():
    for n, word, obj in NUMBERS[:12]:
        page = books_v2.numbers_pages(n, word, obj, _blob())[0]
        a = (np.asarray(page)[1250:] < 128).astype(np.uint8)
        import cv2
        k, _, st, _ = cv2.connectedComponentsWithStats(a, connectivity=8)
        big = sum(1 for i in range(1, k) if st[i, cv2.CC_STAT_AREA] > 2000)
        assert big == n, (n, big)


def test_plurals_read_naturally():
    assert books_v2.plural(1, "duck") == "duck"
    assert books_v2.plural(3, "butterfly") == "butterflies"
    assert books_v2.plural(15, "leaf") == "leaves"
    assert books_v2.plural(12, "fish") == "fish"
    assert books_v2.plural(4, "cupcake") == "cupcakes"


def test_fact_book_build_puts_the_fact_under_each_picture(monkeypatch, tmp_path):
    from engine import bookart
    monkeypatch.setattr(books_v2, "PROD", tmp_path)
    captions = []
    real = books_v2.design_page
    monkeypatch.setattr(books_v2, "design_page", lambda art, caption="": captions.append(caption) or real(art, caption))
    calls = iter(range(10_000))

    def fake_page(subj, **kw):
        im = Image.new("L", books_v2.ART, 255)
        ImageDraw.Draw(im).rectangle((100 + next(calls) % 50, 100, 900, 900), outline=0, width=12)
        return bookart.Page(im, subj, 1, "test", {"regions": 9, "ink": 0.05})
    monkeypatch.setattr(bookart, "page", fake_page)
    res = books_v2.build("ocean_animals", pages=3, log=lambda m: None)
    assert res and captions[:3] == [f"Fun fact: {f}" for _, f in BOOKS["ocean_animals"]["subjects"][:3]]


# ---------------- print-art cleaning (18 Nov: first FLUX page had a solid black penguin + shading marks) ----------
def _cartoon():
    im = Image.new("RGB", (640, 832), "white")
    d = ImageDraw.Draw(im)
    d.ellipse((120, 150, 520, 750), fill=(30, 30, 30), outline=(0, 0, 0), width=6)      # black body
    d.ellipse((220, 300, 420, 700), fill=(255, 255, 255), outline=(0, 0, 0), width=6)   # white belly
    d.rectangle((40, 40, 200, 120), fill=(244, 170, 190))                               # pastel shading, no outline
    d.ellipse((300, 220, 330, 250), fill=(0, 0, 0))                                     # a pupil
    return im


def test_solid_black_fills_become_outlines_but_pupils_stay():
    from engine import bookart
    art = bookart.clean(_cartoon(), page_px=(1125, 1350), stroke=9)
    s = bookart.stats(art)
    assert s["blob"] < 0.01
    a = np.asarray(art)
    assert (a < 128).mean() < 0.2                                  # the body is an outline now, not a blob


def test_pastel_colour_without_outline_is_not_ink():
    from engine import bookart
    im = Image.new("RGB", (640, 832), "white")
    ImageDraw.Draw(im).rectangle((100, 100, 500, 700), fill=(244, 170, 190))
    ImageDraw.Draw(im).ellipse((250, 300, 350, 400), outline=(0, 0, 0), width=8)
    art = bookart.clean(im, page_px=(1125, 1350), stroke=9)
    ys, xs = np.nonzero(np.asarray(art) < 128)
    w, h = xs.max() - xs.min(), ys.max() - ys.min()
    assert 0.85 < w / h < 1.15                                     # only the round outline is ink, not the pink box


def test_colour_by_number_takes_colours_from_the_picture():
    from engine import bookart
    art, col = bookart.clean(_cartoon(), page_px=(1125, 1350), stroke=9, with_colour=True)
    assert col.size == art.size
    names = [n for n, _ in books_v2.CBN_COLORS]
    assert names[books_v2.nearest_key((30, 30, 30))] == "Gray"
    assert names[books_v2.nearest_key((244, 170, 190))] == "Pink"
    assert names[books_v2.nearest_key((255, 214, 90))] == "Yellow"
    assert books_v2.nearest_key((250, 250, 250)) is None           # white stays white (no number)
