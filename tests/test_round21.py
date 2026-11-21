"""Round 21 (14 Nov): store products as an automated flow: covers that sell, catchy titles, descriptions per
product and platform, shop links in descriptions."""
import json

from engine import store_copy, store_covers, store_publish


def test_titles_are_catchy_and_fit_the_store_limit():
    for pid, t in store_covers.TITLES.items():
        assert len(t) <= 100 and "|" in t, pid                 # what it is | who/what for | search words


def test_descriptions_differ_by_platform():
    pay = store_copy.description("bloop_colouring_book", "payhip")
    kdp = store_copy.description("bloop_colouring_book", "kdp")
    soc = store_copy.description("bloop_colouring_book", "social")
    assert "WHAT'S INSIDE" in pay and "Instant download" in pay
    assert "download" not in kdp.lower() and "$" not in kdp       # Amazon book text: no links, prices or downloads
    assert len(soc) < 90
    assert "purchase. Questions" in pay                           # spacing bug fixed


def test_music_copy_states_the_licence():
    d = store_copy.description("music_pack_dhol", "payhip")
    assert "Content ID-free" in d and "Reselling" in d and "90 seconds" in d


def test_every_product_has_cover_spec_and_copy():
    for pid in store_covers.SPECS:
        assert store_copy.copy_for(pid), pid
        assert pid in store_covers.TITLES


def test_shop_link_uses_the_channels_product(tmp_path, monkeypatch):
    # self-contained (the cloud has no data/products: this test failed on GitHub 14 Nov)
    monkeypatch.setattr(store_publish, "PROD", tmp_path)
    monkeypatch.setattr(store_publish, "LISTED", tmp_path / "listed.json")
    (tmp_path / "money_budget_planner").mkdir()
    (tmp_path / "money_budget_planner" / "product.json").write_text(json.dumps(
        {"channel": "money_cheat_codes", "title": "Budget Planner"}), encoding="utf-8")
    (tmp_path / "listed.json").write_text(json.dumps(
        {"money_budget_planner": {"payhip": {"public": "https://payhip.com/b/abc"}}}), encoding="utf-8")
    cap, url = store_publish.shop_link("money_cheat_codes")
    assert url == "https://payhip.com/b/abc" and "Budget Planner" in cap
    assert store_publish.shop_link("clutch_tales") is None


def test_cloud_reads_the_committed_shop_links(tmp_path, monkeypatch):
    monkeypatch.setattr(store_publish, "PROD", tmp_path / "none")            # no product kits (cloud)
    monkeypatch.setattr(store_publish, "SHOP_LINKS", tmp_path / "shop.json")
    (tmp_path / "shop.json").write_text(json.dumps({"money_cheat_codes": ["Planner", "https://payhip.com/b/x"]}))
    assert store_publish.shop_link("money_cheat_codes") == ("Planner", "https://payhip.com/b/x")
    assert store_publish.shop_link("clutch_tales") is None


def test_footer_adds_shop_line(tmp_path, monkeypatch):
    from engine import links
    monkeypatch.setattr(store_publish, "shop_link",
                        lambda c, free=False: ("Budget Planner", "https://payhip.com/b/abc")
                        if c == "money_cheat_codes" and not free else None)
    monkeypatch.setattr(links, "data", lambda: {"money_cheat_codes": {"youtube": "@x", "live": True}})
    assert "🛍️" in links.footer("money_cheat_codes") and "payhip.com/b/abc" in links.footer("money_cheat_codes")
    assert links.footer("money_cheat_codes", kids=True) == ""


def test_kdp_spine_and_listing_rules():
    from engine import kdp
    assert kdp.spine_in(44) == round(44 * 0.002252, 4)
    for pid, b in kdp.BOOKS.items():
        assert len(b["keywords"]) == 7 and len(b["title"]) + len(b["subtitle"]) < 200, pid   # KDP limits
        assert "download" not in store_copy.description(pid, "kdp").lower()


def test_pin_queue_alternates_products_and_skips_posted(tmp_path, monkeypatch):
    from engine import pinterest_post as pp
    monkeypatch.setattr(pp, "PROD", tmp_path)
    monkeypatch.setattr("engine.store_publish.listed", lambda: {     # 22 Nov: only products on sale get pinned
        p: {"payhip": {"public": f"https://payhip.com/b/{p}"}} for p in ("planner_2027", "money_budget_planner")})
    for pid in ("planner_2027", "money_budget_planner", "debt_payoff_planner"):
        d = tmp_path / pid / "pins"
        d.mkdir(parents=True)
        (d / "pins.json").write_text(json.dumps({"board": "B", "link": "L", "pins": [
            {"image": "pins/pin_1.jpg", "title": "t1", "description": "d", "posted": "x" if pid == "planner_2027" else None},
            {"image": "pins/pin_2.jpg", "title": "t2", "description": "d"}]}), encoding="utf-8")
    q = [(pid, k) for pid, k, _, _ in pp.queue()]
    assert q == [("money_budget_planner", 0), ("planner_2027", 1), ("money_budget_planner", 1)]   # the kit is not
    # on sale yet: none of its pins are queued


def test_daily_pins_runs_once_a_day(tmp_path, monkeypatch):
    from engine.cloud import runner
    monkeypatch.setattr(runner, "PIN_STATE", tmp_path / "pins_day.txt")
    (tmp_path / "pins_day.txt").write_text(__import__("time").strftime("%Y-%m-%d"), encoding="utf-8")
    assert runner._daily_pins(log=lambda m: None) == 0
