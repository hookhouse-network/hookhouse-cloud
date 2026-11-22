"""22 Nov: the Savings Challenge Kit came back as "listed on Payhip" (the page had moved to /product/addit after Save) but
Payhip never created it; only the product list shows it for sure. payhip_add now returns the product's edit link from
the dashboard, or raises."""
import pytest

from engine import store_publish as sp


class El:
    def __init__(self, page):
        self.page = page
        self.first = self

    def count(self):
        return 2

    def nth(self, i):
        return self

    def evaluate(self, js):
        return True

    def set_input_files(self, *a, **k):
        self.page.calls.append("file")

    def filter(self, **k):
        return self

    def click(self):
        self.page.calls.append("editor")


class Page:
    def __init__(self):
        self.calls, self.url = [], "https://payhip.com/product/add/digital"

    class keyboard:  # noqa: N801 - the Playwright attribute name
        @staticmethod
        def type(text, delay=0):
            return None

    def goto(self, url, **k):
        self.url = url

    def wait_for_timeout(self, ms):
        return None

    def locator(self, sel):
        return El(self)

    def fill(self, sel, value):
        self.calls.append(sel)

    def click(self, sel):
        self.calls.append(sel)
        self.url = "https://payhip.com/product/addit"          # what Payhip shows right after Save

    def evaluate(self, js):
        if "innerText" in js and "alert" not in js:
            return "Saving..."
        return "" if "alert" in js else False


@pytest.fixture
def kit(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "PROD", tmp_path)
    (tmp_path / "kit").mkdir()
    monkeypatch.setattr(sp, "download_file", lambda pid: tmp_path / "kit" / "kit.zip")
    monkeypatch.setattr(sp, "_upload_timeout", lambda path: 1000)
    monkeypatch.setattr(sp, "title_for", lambda pid: "Savings Challenge Printable | 52 Week Money Challenge")
    monkeypatch.setattr(sp, "price_usd", lambda pid: 4.0)
    monkeypatch.setattr(sp, "description_for", lambda pid: "Small amounts, saved every week.")
    return Page()


def test_listed_only_when_the_product_is_on_the_dashboard(kit, monkeypatch):
    rows = [("https://payhip.com/product/edit/OLD1", "Debt Payoff Planner Printable | Debt Snowball & ...", "")]
    seen = iter([rows, rows + [("https://payhip.com/product/edit/DSeLF",
                                "Savings Challenge Printable | 52 Week Money Ch...", "https://payhip.com/b/DSeLF")]])
    monkeypatch.setattr(sp, "payhip_rows", lambda p: next(seen))
    assert sp.payhip_add(kit, "savings_challenge_tracker") == "https://payhip.com/product/edit/DSeLF"
    assert "#addsubmit" in kit.calls


def test_a_save_that_never_shows_up_is_a_failure_not_a_listing(kit, monkeypatch):
    monkeypatch.setattr(sp, "payhip_rows", lambda p: [])
    with pytest.raises(RuntimeError, match="did not create the product"):
        sp.payhip_add(kit, "savings_challenge_tracker")
