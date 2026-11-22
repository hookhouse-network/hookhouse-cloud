"""23 Nov, P3b picture-free scenes: a "depth" chart for ocean stories. The camera sinks from the surface to the spoken
depth past real landmarks (names only), the gauge climbs to the spoken number, the water darkens by the real light
zones. Deep Blue Files' 23 Nov Short said "found 2,000 feet down" and showed a local AI picture there."""
import json
import subprocess
from pathlib import Path

from engine.media import html_scene as hs

NARR = "This is the Barreleye, a deep-sea creature found 2,000 feet down."


def test_the_depth_comes_from_the_spoken_words():
    assert round(hs.depth_m("2,000 feet")) == 610 and hs.depth_m("3.8 km") == 3800.0
    assert hs.depth_m("200 metres") == 200.0 and hs.depth_m("12,500 ft") == 3810.0
    assert round(hs.depth_m("7 miles")) == 11265 and hs.depth_m("deep down") is None


def test_check_chart_depth():
    ok, why = hs.check_chart({"type": "depth", "items": [{"label": "Barreleye", "text": "2,000 feet"}]}, NARR)
    assert why == "" and ok["items"] == [{"label": "Barreleye", "text": "2,000 feet", "value": 609.6}]
    assert [m["label"] for m in ok["marks"]][:2] == ["Scuba divers' limit", "Sunlight fades out"]
    assert all("m" in m and not any(ch.isdigit() for ch in m["label"]) for m in ok["marks"])   # names only
    bad = [({"type": "depth", "items": [{"label": "Barreleye", "text": "3,000 feet"}]}, "never said"),
           ({"type": "depth", "items": [{"label": "Barreleye", "text": "2,000"}]}, "unit"),
           ({"type": "depth", "items": [{"label": "A", "text": "2,000 feet"}, {"label": "B", "text": "2,000 feet"}]},
            "1-1 items"),
           ({"type": "depth", "items": [{"label": "Moon", "text": "2,000 km"}]}, "not an ocean depth")]
    for chart, reason in bad:
        got, why = hs.check_chart(chart, NARR + " The Moon is 2,000 km away.")
        assert got is None and reason in why, (chart, why)


def _luma(video: Path, at: float) -> float:
    from engine.media import ffmpeg
    raw = subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
                          "-vf", "scale=36:64,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    return sum(raw) / max(1, len(raw))


def test_the_dive_records_and_the_water_darkens(tmp_path):
    from engine.media import ffmpeg
    chart, _ = hs.check_chart({"type": "depth", "items": [{"label": "Barreleye", "text": "2,000 feet"}]}, NARR)
    out = hs.chart_video({"id": "deep_blue_files", "language": "en"}, chart, (360, 640), 3.0, tmp_path / "d.mp4",
                         fps=10)
    assert out.exists() and 2.9 <= ffmpeg.duration(out) <= 3.1
    assert _luma(out, 0.0) > _luma(out, 2.8) + 25                 # surface light at the start, dark at 600 m


def test_the_story_prompt_offers_the_depth_dive():
    from engine import story
    src = Path(story.__file__).read_text(encoding="utf-8")
    assert '"type": "compare|timeline|scale|depth|map"' in src and "WITH its unit" in src   # 23 Nov: + map
    json.dumps({"ok": True})
