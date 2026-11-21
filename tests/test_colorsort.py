"""P3r step 3 / S3 (owner 21 Nov: "we need more self satisfactory content"): the colour-sort Brain Snack format,
drawn in HTML/CSS and rendered by HyperFrames; deterministic, loops, every swap a note."""
import numpy as np
import pytest

from engine.media import hyperframes as hf
from engine.snack import audio as au, colorsort as cs

SPEC = {"format": "colorsort", "seed": 4242, "layout": 1, "hue_shift": 0.3, "instrument": "marimba"}


def test_plan_sorts_everything_and_is_deterministic():
    p = cs.plan(SPEC)
    assert p == cs.plan(dict(SPEC))
    cols, rows = cs.LAYOUTS[1]
    assert p["n"] == cols * rows and sorted(p["start"]) == list(range(p["n"]))
    cur = list(p["start"])
    for mv in p["moves"]:
        cur[mv["a"]], cur[mv["b"]] = cur[mv["b"]], cur[mv["a"]]
    assert cur == list(range(p["n"]))                       # the swaps really sort the grid
    assert len(p["moves"]) <= p["n"] - 1
    ts = [mv["t"] for mv in p["moves"]]
    assert ts == sorted(ts) and ts[0] == cs.INTRO_S
    assert [mv["d"] for mv in p["moves"][-3:]] == list(cs.SUSPENSE)      # "wait for the last tile"
    middle = [mv["d"] for mv in p["moves"][:-3]]
    assert middle[0] == cs.FAST and min(middle) == pytest.approx(cs.SLOW, abs=1e-3)
    assert p["total"] == pytest.approx(p["t_done"] + cs.WAVE_S + cs.BACK_S)
    assert cs.plan(dict(SPEC, seed=7))["start"] != p["start"]


def test_every_tile_loops_back_to_its_start():
    p = cs.plan(SPEC)
    keys = cs.tracks(p)
    for k, frames in keys.items():
        start_xy = cs._xy(p["start"].index(k), p["cols"], p["rows"])
        assert frames[0][1:3] == start_xy and frames[-1][1:3] == start_xy and frames[-1][0] == p["total"]
        done = [f for f in frames if f[0] > p["t_done"]][0]
        assert done[1:3] == cs._xy(k, p["cols"], p["rows"])               # in its rainbow place when done
        assert [f[0] for f in frames] == sorted(f[0] for f in frames)


def test_composition_follows_the_house_rules():
    p = cs.plan(SPEC)
    page = cs.html(p, "Watch it sort itself")
    assert hf.lint_html(page) == []
    assert hf.spec(page) == {"w": 1080, "h": 1920, "dur": p["total"]}
    assert page.count('class="clip tile"') == p["n"] and "gsap" not in page.lower()
    assert cs.colour(0, 10, 0.0) != cs.colour(9, 10, 0.0)
    # seamless loop: "100% sorted" fades out and the progress bar empties before the last frame
    assert "100%{opacity:0;transform:scale(.6)}" in page and "100%{width:0%}" in page
    assert page.index("@keyframes bar") < page.index("100%{width:0%}")


def test_only_a_machine_with_hyperframes_picks_it(monkeypatch):
    from engine.snack import maker
    monkeypatch.setattr(hf, "available", lambda: False)
    assert "colorsort" not in maker.ready_formats()
    assert all(maker.choose_format([], made=["spiral", "versus"]) != "colorsort" for _ in range(60))
    monkeypatch.setattr(hf, "available", lambda: True)
    assert "colorsort" in maker.ready_formats()
    monkeypatch.setattr("engine.config.settings", lambda: {"hyperframes_formats": False})      # the off-switch
    assert "colorsort" not in maker.ready_formats()
    monkeypatch.setattr("engine.config.settings", lambda: {"hyperframes_formats": True})
    picks = {maker.choose_format([], made=["spiral", "versus"]) for _ in range(120)}
    assert "colorsort" in picks


def test_maker_spec_titles_and_description():
    from engine.snack import maker
    spec = maker.new_spec("colorsort", [], seed=11)
    assert spec["format"] == "colorsort" and spec["layout"] in range(len(cs.LAYOUTS)) and 0 <= spec["hue_shift"] < 1
    assert any("last tile" in t for t in maker.titles_for(spec))
    q, send = maker.cta_for("colorsort")
    assert q.endswith("👇") and send.startswith("Send it to")
    assert "no AI" in maker.MADE_WITH["colorsort"] and "collision" not in maker.MADE_WITH["colorsort"]


def test_every_format_describes_what_the_viewer_sees(tmp_path):
    """21 Nov: the judge got "spiral spiral speed twinkle marimba" for our best format and scored hook 3/10."""
    from engine import potential_gate as pg
    from engine.snack import maker
    cases = {
        "spiral": ({"format": "spiral", "rule": "speed", "melody": "twinkle"}, {"total": 28.0, "attempts": 5,
                                                                              "win_at": 24.2}),
        "multiply": ({"format": "multiply", "shape": "heart"}, {"total": 30.0, "t_fill": 21.5, "balls": 512}),
        "versus": ({"format": "versus", "pair": "Lava|Ice"}, {"total": 25.0, "winner": "Ice", "loser": "Lava",
                                                              "ko_at": 19.0}),
        "ladder": ({"format": "ladder", "category": "food", "quiz": {"questions": [{"q": "Which fruit is a berry?"}]}},
                   {"total": 42.0}),
        "readfast": ({"format": "readfast", "fact": {"fact": "Octopuses have three hearts."}}, {"total": 20, "words": 30}),
        "colorsort": ({"format": "colorsort"}, {"total": 18.9, "tiles": 77, "swaps": 74, "t_done": 16.8}),
    }
    for fmt, (spec, info) in cases.items():
        text = maker.describe(spec, info)
        assert len(text) > 80 and "None" not in text, fmt
    assert "5 times" in maker.describe(*cases["spiral"]) and "0:24" in maker.describe(*cases["spiral"])
    assert "Ice knocks out Lava at 0:19" in maker.describe(*cases["versus"])
    assert "77 colour tiles" in maker.describe(*cases["colorsort"]) and "0:16" in maker.describe(*cases["colorsort"])
    (tmp_path / "script.json").write_text('{"title": "spiral", "shown": "A glowing ball drops", "spec": {}}',
                                          encoding="utf-8")
    assert pg.script_text({"out_dir": str(tmp_path), "file": "video.mp4"}, {}) == "A glowing ball drops"
    page = pg._prompt({"name": "Brain Snack", "niche": "satisfying"}, {"topic": ""},
                      {"title": "Wait for the last try", "hook_text": "Which try reaches the center?"}, "brainrot",
                      ["hook"], "")
    assert "HOOK / FIRST LINE: Which try reaches the center?" in page


def test_render_spec_runs_the_format(tmp_path, monkeypatch):
    from engine.snack import maker

    def fake_render(spec, work, log=print, hf=None):
        (work / "anim.mp4").write_bytes(b"x")
        return {"total": 2.0, "t_done": 1.0, "swaps": 1, "moves": [(0.5, 1.0)], "cover_at": 1.5, "ai_voice": False}
    monkeypatch.setattr(cs, "render", fake_render)
    muxed = []
    monkeypatch.setattr(maker, "mux", lambda silent, mix, final, work: muxed.append((silent, final)))
    info = maker.render_spec(dict(SPEC), tmp_path)
    assert info["fps"] == 30 and info["ai_voice"] is False
    assert muxed[0][0] == tmp_path / "work" / "anim.mp4" and muxed[0][1] == tmp_path / "video.mp4"


def test_render_and_soundtrack(tmp_path):
    class FakeHF:
        def __init__(self):
            self.rendered = None

        def write_project(self, work, page, assets=None):
            return hf.write_project(work, page, assets)

        def render(self, project, out, log=print):
            self.rendered = (project, out)
            out.write_bytes(b"x" * 2048)
            return out
    fake = FakeHF()
    info = cs.render(SPEC, tmp_path, log=lambda *_: None, hf=fake)
    assert fake.rendered[1] == tmp_path / "anim.mp4" and (tmp_path / "hf" / "index.html").exists()
    assert info["swaps"] == len(info["moves"]) and info["ai_voice"] is False
    assert info["t_done"] < info["cover_at"] < info["total"]
    mix = cs.soundtrack(info, SPEC)
    assert abs(len(mix) - int(info["total"] * au.SR)) <= au.SR // 10 and np.isfinite(mix).all() and np.abs(mix).max() > 0
