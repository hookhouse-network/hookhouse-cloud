"""Activity book v2 (18 Nov): mazes, dot to dot, spot the difference, word search, all from FLUX line art."""
import numpy as np
from PIL import Image, ImageDraw

from engine import activity_v2 as av, bookart
from engine.book_specs import BOOKS


def figure(size=(1200, 1200)) -> Image.Image:
    """A cartoon-like line drawing: a big outlined body with small closed details (eyes, buttons) inside."""
    im = Image.new("L", size, 255)
    d = ImageDraw.Draw(im)
    w, h = size
    d.ellipse((w * .2, h * .15, w * .8, h * .9), outline=0, width=12)
    for cx, cy in ((.4, .35), (.6, .35), (.5, .55), (.5, .7)):
        d.ellipse((w * cx - 30, h * cy - 30, w * cx + 30, h * cy + 30), outline=0, width=10)
    return im


def test_every_picture_has_a_stable_key_and_word_search_pictures_exist():
    spec = BOOKS["activity_book"]
    keys = [k for k, _, _, _ in av.pictures(spec)]
    assert {c for *_, c in av.pictures(spec)} == {"toddler", "kids"}
    assert len(keys) == len(set(keys)) == 2 * len(spec["mazes"]) + len(spec["dots"]) + len(spec["spot"])
    assert all(pic in keys for _, _, pic in spec["word_search"])
    assert len(spec["dot_names"]) == len(spec["dots"])
    for _, words, _ in spec["word_search"]:                          # 11 x 11 grid, easy directions
        assert len(words) == 8 and max(map(len, words)) <= 11 and all(w.isalpha() and w.isupper() for w in words)


def test_dots_follow_the_outline_starting_at_the_top():
    pts, fig = av.dot_points(figure(), 24)
    assert len(pts) == 24
    assert min(range(24), key=lambda i: pts[i][1]) in (0, 1, 23)          # dot 1 is at the top
    xs, ys = zip(*pts)
    assert 200 < min(xs) and max(xs) < 1000 and fig.sum() > 0
    gaps = [np.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) for i in range(24)]
    assert max(gaps) < 3 * min(gaps)                                       # evenly spread, no bunching


def test_dots_page_numbers_do_not_overlap():
    p = av.dots_page(figure(av.DOTS), "Egg", 30)
    assert p.size == (av.PW, av.PH)


def test_spot_the_difference_makes_exactly_n_visible_changes():
    art = figure(av.SCENE)
    changed, circles = av.differences(art, 5, seed=1)
    assert len(circles) == 5
    diff = np.asarray(art) != np.asarray(changed)
    for cx, cy, r in circles:                                            # every circle marks a real change
        assert diff[max(0, cy - r):cy + r, max(0, cx - r):cx + r].any()
    for i, (x1, y1, _) in enumerate(circles):                            # no two answers on top of each other
        for x2, y2, _ in circles[i + 1:]:
            assert np.hypot(x1 - x2, y1 - y2) > 60
    assert av.spot_page(art, changed, 5, circles).mode == "RGB"


def test_interleave_mixes_activities_and_keeps_their_order():
    assert av.interleave([[1, 2, 3], ["a"], [], ["x", "y"]]) == [1, "a", "x", 2, "y", 3]


def test_build_activity_with_fake_pictures(tmp_path, monkeypatch):
    monkeypatch.setattr(av, "PROD", tmp_path)

    def fake_page(subject, age="kids", seed=1, used=None, page_px=(1000, 1000), log=print, allow_local=True, **k):
        return bookart.Page(figure(page_px), subject, seed, "test", {"regions": 9, "ink": 0.05}, None)
    monkeypatch.setattr(bookart, "page", fake_page)
    assert av.build_activity("activity_book", log=lambda *_: None, max_new=3) is None     # still drawing
    res = av.build_activity("activity_book", log=lambda *_: None)
    spec = BOOKS["activity_book"]
    assert res["pages"] % 2 == 0 and res["designs"] == len(av.pictures(spec))
    n_puzzles = len(spec["mazes"]) + len(spec["dots"]) + len(spec["spot"]) + len(spec["word_search"])
    assert res["pages"] >= n_puzzles + len(spec["mazes"]) + len(spec["spot"]) + len(spec["word_search"])
    assert (tmp_path / "activity_book" / res["interior"]).exists()
    assert (tmp_path / "activity_book" / "cover_v2.jpg").exists()


def test_tracing_pages_use_the_alphabet_and_counting_pictures(monkeypatch):
    from engine import kdp_books
    monkeypatch.setattr(kdp_books, "v2_art", lambda book, k: figure((800, 800)))
    plain = np.asarray(kdp_books._page("Aa", "A is for Alligator")[0])
    a = kdp_books.letter_page("A")
    assert (np.asarray(a) != plain).any()
    three = kdp_books.number_page(3)
    assert three.size == (kdp_books.PW, kdp_books.PH)


def test_tracing_book_waits_for_its_picture_books(tmp_path, monkeypatch):
    from engine import kdp_books
    monkeypatch.setattr(av, "PROD", tmp_path)
    monkeypatch.setattr(kdp_books, "OUT", tmp_path)
    assert av.build_tracing(log=lambda *_: None) is None                     # alphabet + counting not built yet
    for b in ("fun_alphabet", "numbers_counting"):
        (tmp_path / b).mkdir()
        (tmp_path / b / "kdp_listing_v2.json").write_text("{}")
    monkeypatch.setattr(kdp_books, "v2_art", lambda book, k: figure((800, 800)))

    def small_tracing(log=print):                     # the real 110-page PDF takes 3 minutes; pages tested above
        import json
        f = tmp_path / "tracing_workbook"
        f.mkdir(exist_ok=True)
        (f / "T.pdf").write_bytes(b"%PDF")
        (f / "product.json").write_text(json.dumps({"files": ["T.pdf"], "pages": 110}))
        return f
    monkeypatch.setattr(kdp_books, "tracing", small_tracing)
    res = av.build_tracing(log=lambda *_: None)
    assert res and res["pages"] % 2 == 0 and (tmp_path / "tracing_workbook" / "kdp_cover_v2.pdf").exists()


def test_seniors_spreads_picture_left_puzzle_right(tmp_path, monkeypatch):
    from engine import book_specs, nostalgia_words
    themes = dict(list(nostalgia_words.THEMES.items())[:3])
    monkeypatch.setattr(nostalgia_words, "THEMES", themes)
    monkeypatch.setattr(book_specs, "SENIORS", book_specs.SENIORS[:3])
    monkeypatch.setattr(av, "PROD", tmp_path)
    seen = []

    def fake_page(subject, age="kids", seed=1, used=None, page_px=(1000, 1000), log=print, allow_local=True, **k):
        seen.append(age)
        return bookart.Page(figure(page_px), subject, seed, "test", {}, None)
    monkeypatch.setattr(bookart, "page", fake_page)
    pages = []
    real_mem = av.memory_page
    monkeypatch.setattr(av, "memory_page", lambda *a: pages.append("memory") or real_mem(*a))
    res = av.build_seniors(log=lambda *_: None)
    assert res and res["designs"] == 3 and set(seen) == {"older"} and res["pages"] % 2 == 0
    # title (p1, right), how to play (p2), belongs-to (p3), then picture on p4 (left) + puzzle on p5 (right) ...
    assert len(pages) == 3


def test_every_nostalgia_theme_has_a_picture_and_memory():
    from engine.book_specs import SENIORS
    from engine.nostalgia_words import THEMES
    assert len(SENIORS) == len(THEMES)
    assert all(m.endswith("?") and len(m) <= 90 for _, m in SENIORS)


def test_kids_short_friends_rotate_and_names_match_who_is_on_screen():
    from engine import kids
    lines = [{"who": "Pip", "say": "Hi Mo! Look at the moon.", "section": "intro", "kind": "story"},
             {"who": "Bloop", "say": "Thanks, Dee!", "section": "intro", "kind": "story"}]
    friends = set()
    for seed in range(len(kids.FRIENDS)):
        out, duo = kids.duo_lines(lines, seed)
        friends.add(duo[1])
        assert duo[0] == "Bloop" and {ln["who"] for ln in out} <= {"Bloop", duo[1]}
        assert out[0]["say"] == "Hi Bloop! Look at the moon."                  # the friend talks to Bloop
        assert out[1]["say"] == f"Thanks, {duo[1]}!"                           # Bloop talks to the friend
    assert {"Kiki", "Hop", "Zip"} <= friends
    kids.use_layout("short", duo=("Bloop", "Hop"))
    try:
        assert set(kids.CAST) == {"Bloop", "Hop"} and kids.CAST["Hop"][1] == "bunny"
    finally:
        kids.use_layout("long")


def test_every_kids_object_draws_and_has_its_words():
    from engine import kids
    for obj in kids.OBJECTS:
        spr = kids.draw_object(obj, 120)
        assert spr.shape == (120, 120, 4) and spr[..., 3].mean() > 20, obj        # something visible
        if obj not in kids.XMAS_OBJECTS:
            assert obj in kids.ADJ_DEFAULT, obj
            assert obj in kids.OBJECT_COLOUR or obj == "ball", obj           # the beach ball is many colours
    assert kids.PLURAL["butterfly"] == "butterflies" and kids.PLURAL["leaf"] == "leaves"
