"""Round 22 (14 Nov): KDP book family: research-led books, page decorations, color by number, one-command pipeline."""
import numpy as np
from PIL import Image

from engine import kdp, kdp_books, product_factory, store_copy, store_covers


def test_decorate_adds_header_footer_and_rating():
    pages = [Image.new("RGB", (kdp_books.PW, kdp_books.PH), "white") for _ in range(3)]
    out = kdp_books.decorate(pages, "Test Book", skip_first=1)
    first, second = np.array(out[0]), np.array(out[1])
    assert first.min() == 255                                   # cover untouched
    assert second[kdp_books.PH - 160:].min() < 200              # footer drawn (page number, line, stars)


def test_qr_page_is_off_until_the_channel_is_live():
    assert kdp_books.WATCH_QR is False                          # owner: roadmap, no QR yet


def test_color_by_number_regions_and_legend():
    spr = np.zeros((200, 200, 4), np.uint8)
    spr[20:180, 20:180] = (40, 40, 220, 255)                    # red body (BGRA)
    spr[20:60, 80:120] = (60, 170, 70, 255)                     # green leaf
    spr[18:22, 18:182] = (20, 20, 20, 255)                      # black outline -> a line, not a color
    L, legend = kdp_books.cbn_regions(spr, 400)
    assert "Red" in legend.values() and "Green" in legend.values() and "Black" not in legend.values()


def test_every_book_is_wired_end_to_end():
    for pid in product_factory.BUILDERS:
        assert pid in store_covers.SPECS and pid in store_covers.TITLES and store_copy.copy_for(pid), pid
    for pid in ("tracing_workbook", "color_by_number"):
        b = kdp.BOOKS[pid]
        assert b["price"] >= 9.99                               # KDP's 60% royalty tier
        assert len(b["keywords"]) == 7
