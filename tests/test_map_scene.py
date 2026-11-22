"""23 Nov, P3b picture-free scenes: a "map" chart. The globe turns to the place the narrator names, dives in and drops
a pin with its name. The point comes from the place's Wikipedia article (never from the writer); land, lakes, borders,
states and rivers are Natural Earth 1:50m (public domain). Word cards held Unsolved After Dark (9/10 shots) and
Picture Abhi Baaki Hai; a crime or history story nearly always says where it happened."""
import json
import subprocess
from pathlib import Path

import pytest

from engine.media import html_scene as hs

NARR = "It all started in Point Pleasant, a quiet river town, in November 1966."
CHART = {"type": "map", "items": [{"label": "Point Pleasant", "text": "West Virginia",
                                   "place": "Point Pleasant, West Virginia"}]}


def test_check_chart_map_needs_the_place_said_and_no_unspoken_numbers():
    ok, why = hs.check_chart(CHART, NARR)
    assert why == "" and ok["items"] == [{"label": "Point Pleasant", "text": "West Virginia",
                                          "place": "Point Pleasant, West Virginia"}]
    bad = [({"type": "map", "items": [{"label": "Mothman Town", "text": "West Virginia"}]}, "never said"),
           ({"type": "map", "items": [{"label": "Point Pleasant", "text": "Route 62"}]}, "62 is shown but never said"),
           ({"type": "map", "items": [{"label": "A"}, {"label": "B"}]}, "1-1 items")]
    for chart, reason in bad:
        got, why = hs.check_chart(chart, NARR)
        assert got is None and reason in why, (chart, why)


def test_place_names_match_as_heard_in_english_and_hindi():
    assert hs.place_said("Point Pleasant", "It started in point pleasant.")
    assert hs.place_said("The Mariana Trench", "Down in the Mariana Trench's dark")
    assert not hs.place_said("Point Pleasant", "It started in a pleasant town")
    assert hs.place_said("द्वारका", "समुद्र के नीचे द्वारका की कहानी")          # vowel signs are part of the word
    assert not hs.place_said("द्वारका", "समुद्र के नीचे मथुरा की कहानी")


def _wiki(pages: dict, search: list | None = None):
    """A fake Wikipedia API: titles -> page dicts; list=search -> the given titles."""
    calls = []

    def get(url, params):
        calls.append((url, dict(params)))
        if params.get("list") == "search":
            return {"query": {"search": [{"title": t} for t in search or []]}}
        page = pages.get(params["titles"], {"missing": ""})
        return {"query": {"pages": {"1": dict(page, title=params["titles"])}}}
    return get, calls


PP = {"coordinates": [{"lat": 38.8575, "lon": -82.1286, "type": "city(4350)", "primary": ""}],
      "description": "City in West Virginia, United States"}


def test_locate_takes_the_point_and_subtitle_from_wikipedia():
    get, calls = _wiki({"Point Pleasant, West Virginia": PP})
    chart, why = hs.locate(hs.check_chart(CHART, NARR)[0], get=get)
    it = chart["items"][0]
    assert why == "" and (it["lat"], it["lon"]) == (38.8575, -82.1286) and it["span_km"] == 900
    assert it["text"] == "City in West Virginia, United States" and it["label"] == "Point Pleasant"
    assert calls[0][0] == "https://en.wikipedia.org/w/api.php" and calls[0][1]["redirects"] == 1


def test_a_hindi_channel_keeps_its_own_subtitle_and_numbers_never_come_from_a_description():
    get, _ = _wiki({"Dwarka": dict(PP, description="Ancient city, founded 3000 BC")})
    hi = {"type": "map", "items": [{"label": "द्वारका", "text": "गुजरात, भारत", "place": "Dwarka"}]}
    chart, _ = hs.locate(hi, language="hi", get=get)
    assert chart["items"][0]["text"] == "गुजरात, भारत"
    chart, _ = hs.locate({"type": "map", "items": [{"label": "Dwarka", "text": "Gujarat", "place": "Dwarka"}]}, get=get)
    assert chart["items"][0]["text"] == "Gujarat"                           # "3000 BC" is never said: not shown


def test_a_disambiguation_page_falls_back_to_a_search_hit_that_shares_the_name():
    pages = {"Point Pleasant": {"pageprops": {"disambiguation": ""}},
             "Point Pleasant, West Virginia": PP}
    get, _ = _wiki(pages, search=["Mothman", "Point Pleasant, West Virginia"])
    chart, why = hs.locate({"type": "map", "items": [{"label": "Point Pleasant", "text": "", "place": "Point Pleasant"}]},
                           get=get)
    assert why == "" and chart["items"][0]["wiki"] == "Point Pleasant, West Virginia"


def test_no_single_point_or_no_network_means_no_map():
    get, _ = _wiki({}, search=["Something Else"])
    chart, why = hs.locate(hs.check_chart(CHART, NARR)[0], get=get)
    assert chart is None and "no single point" in why

    def down(url, params):
        raise ConnectionError("offline")
    chart, why = hs.locate(hs.check_chart(CHART, NARR)[0], get=down)
    assert chart is None and "lookup failed" in why


def test_the_frame_width_follows_the_place_size():
    assert hs.span_km({"type": "country"}) == 3200 and hs.span_km({"type": "city(30000)"}) == 900
    assert hs.span_km({"type": "", "dim": 1_000_000}) == 2500 and hs.span_km({"dim": 1000}) == 800
    assert hs.span_km({}) == 1500


def test_the_world_file_is_public_domain_natural_earth_and_compact():
    w = hs.world()
    assert "Natural Earth" in w["src"] and "public domain" in w["src"]
    assert len(w["land"]) > 1000 and w["lakes"] and w["borders"] and w["states"] and w["rivers"]
    assert hs.WORLD_FILE.stat().st_size < 600_000


# --- the drawing: land is land and sea is sea from every side of the globe ---------------------------------------
LAND = [(10, 23), (100, 62), (-55, -10), (-100, 40), (134, -25), (25, -25), (78, 22)]
SEA = [(-150, 0), (170, -20), (-30, 30), (75, -20), (-130, -40), (60, 10), (150, 25)]


def _page(tmp_path, chart):
    th = hs.theme_for({"id": "unsolved_after_dark", "language": "en"})
    payload = dict(chart, world=hs.world(), width=360, height=640, seconds=3.0, theme=th)
    html = (hs.SCENES / "chart.html").read_text(encoding="utf-8")
    html = html.replace("/*FONTS*/", hs._font_css(th)).replace("/*DATA*/{}", json.dumps(payload, ensure_ascii=False))
    f = tmp_path / "map.html"
    f.write_text(html, encoding="utf-8")
    return f


def test_land_and_sea_fill_correctly_from_every_side(tmp_path):
    """The limb clamp alone painted the sea as land when the Americas held the point behind the globe (Dwarka's spin
    passed over Asia); the antipode flip fixes it. Checked with the canvas's own even-odd hit test."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    chart = {"type": "map", "items": [{"label": "X", "text": "", "lat": 0, "lon": 0, "span_km": 1500}]}
    f = _page(tmp_path, chart)
    with sync_playwright() as pw:
        browser = hs._launch(pw)
        try:
            page = browser.new_page(viewport={"width": 360, "height": 640})
            page.goto(f.as_uri())
            page.evaluate("window.ready")
            wrong = page.evaluate("""([land, sea]) => {
                geo(); const out = [];
                for (let lon = -180; lon < 180; lon += 30) for (const lat of [-25, 0, 20]) {
                  const v = { lam0: lon * DEG, phi0: lat * DEG, R: 150, cx: 180, cy: 320 };
                  areaPath(GEO.land, v); const P = projector(v);
                  const pack = (lo, la) => new Float64Array([Math.sin(lo * DEG), Math.cos(lo * DEG), Math.sin(la * DEG), Math.cos(la * DEG)]);
                  for (const [pts, want] of [[land, true], [sea, false]]) for (const [lo, la] of pts) {
                    const o = P(pack(lo, la), 0);
                    if (o[2] < 0.25) continue;                       // near the edge or behind: not judged
                    const got = g.isPointInPath(180 + 150 * o[0], 320 - 150 * o[1], "evenodd");
                    if (got !== want) out.push([lon, lat, lo, la, want]);
                  }
                }
                return out;
            }""", [LAND, SEA])
        finally:
            browser.close()
    assert wrong == []


def test_the_dive_records_from_globe_to_pin(tmp_path):
    from engine.media import ffmpeg
    get, _ = _wiki({"Point Pleasant, West Virginia": PP})
    chart, _ = hs.locate(hs.check_chart(CHART, NARR)[0], get=get)
    out = hs.chart_video({"id": "unsolved_after_dark", "language": "en"}, chart, (360, 640), 3.0, tmp_path / "m.mp4",
                         fps=10)
    assert out.exists() and 2.9 <= ffmpeg.duration(out) <= 3.1

    def frame(at):
        return subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(out), "-frames:v", "1",
                               "-vf", "scale=36:64,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    start, end = frame(0.0), frame(2.9)
    corners = lambda raw: sum(raw[i] for i in (0, 35, 36 * 63, 36 * 64 - 1)) / 4      # noqa: E731
    assert corners(end) > corners(start) + 20       # space around the globe at the start, land fills the frame at the end


def test_the_story_prompt_offers_the_map():
    from engine import story
    src = Path(story.__file__).read_text(encoding="utf-8")
    assert "names WHERE on Earth the story happens" in src and "exact English Wikipedia article title" in src
    assert "html_scene.locate(chart" in src
