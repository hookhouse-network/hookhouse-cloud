"""P3r step 2 (S9): HyperFrames (Apache-2.0) renders our CSS-only compositions on the PC; every render is checked
against the composition before anything uses it."""
import os
import subprocess

import pytest

from engine.media import hyperframes as hf


def test_spec_and_house_rules():
    html = hf.card_html([("Only 1% get this", 0.0, 1.5), ("Can you?", 1.5, 1.5)], dur=3.0)
    assert hf.spec(html) == {"w": 1080, "h": 1920, "dur": 3.0}
    assert hf.lint_html(html) == []
    assert "Only 1% get this" in html and "infinite" not in html
    with pytest.raises(hf.RenderError):
        hf.spec("<html><body><div id='x'></div></body></html>")
    bad = html.replace(" data-no-timeline", "")
    assert any("data-no-timeline" in p for p in hf.lint_html(bad))
    gs = html.replace("</body>", "<script>gsap.timeline({paused: true})</script></body>")
    assert any("gsap" in p.lower() for p in hf.lint_html(gs))
    loop = html.replace("0s 1 both;", "0s infinite both;", 1)
    assert any("infinite" in p for p in hf.lint_html(loop))
    words = html.replace("Can you?", "An infinite loop of fun")                  # a word, not CSS: fine
    assert hf.lint_html(words) == []
    untimed = html.replace('class="clip card" data-start="0.000"', 'class="clip card"', 1)
    assert any("without data-start" in p for p in hf.lint_html(untimed))
    rnd = html.replace("</body>", "<script>Math.random()</script></body>")
    assert any("Math.random" in p for p in hf.lint_html(rnd))


def test_write_project_copies_assets_and_refuses_broken_compositions(tmp_path):
    pic = tmp_path / "pic.png"
    pic.write_bytes(b"\x89PNG fake")
    html = hf.card_html([("Hi", 0.0, 1.0)])
    proj = hf.write_project(tmp_path / "p", html, assets={"pic.png": pic})
    assert (proj / "index.html").read_text(encoding="utf-8") == html
    assert (proj / "assets" / "pic.png").read_bytes() == b"\x89PNG fake"
    with pytest.raises(hf.RenderError, match="house rules"):
        hf.write_project(tmp_path / "q", html.replace(" data-no-timeline", ""))


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    exe = tmp_path / "hyperframes.cmd"
    exe.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("HH_HYPERFRAMES", str(exe))
    return exe


def _project(tmp_path):
    return hf.write_project(tmp_path / "proj", hf.card_html([("Hi", 0.0, 1.5), ("there", 1.5, 1.5)], dur=3.0))


def test_render_runs_the_pinned_cli_low_priority_and_checks_the_output(tmp_path, fake_cli):
    proj, out = _project(tmp_path), tmp_path / "out" / "v.mp4"
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        out.write_bytes(b"x" * 4096)
        return subprocess.CompletedProcess(cmd, 0, stdout="◇ done\n   rendered in 20.4s\n", stderr="")
    lines = []
    got = hf.render(proj, out, run=run, probe=lambda v: {"w": 1080, "h": 1920, "dur": 3.0}, log=lines.append)
    assert got == out.resolve()
    cmd, kw = calls[0]
    assert cmd[0] == str(fake_cli) and cmd[1:4] == ["render", "--quality", "looks"] and cmd[-1] == str(out.resolve())
    assert kw["cwd"] == str(proj) and kw["timeout"] == 900
    if os.name == "nt":
        assert kw["creationflags"] & 0x00004000                                   # below-normal priority
    assert "in 20.4s" in lines[-1]


@pytest.mark.parametrize("rc, write, probe, match", [
    (1, True, {"w": 1080, "h": 1920, "dur": 3.0}, "exit 1"),
    (0, False, {"w": 1080, "h": 1920, "dur": 3.0}, "wrote no video"),
    (0, True, {"w": 720, "h": 1280, "dur": 3.0}, "720x1280"),
    (0, True, {"w": 1080, "h": 1920, "dur": 2.0}, "2.0s"),
])
def test_a_bad_render_is_never_used(tmp_path, fake_cli, rc, write, probe, match):
    proj, out = _project(tmp_path), tmp_path / "v.mp4"

    def run(cmd, **kw):
        if write:
            out.write_bytes(b"x" * 4096)
        return subprocess.CompletedProcess(cmd, rc, stdout="✗ Chrome crashed", stderr="")
    with pytest.raises(hf.RenderError, match=match):
        hf.render(proj, out, run=run, probe=lambda v: probe, log=lambda *_: None)


def test_timeout_and_missing_cli(tmp_path, fake_cli, monkeypatch):
    proj = _project(tmp_path)

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    with pytest.raises(hf.RenderError, match="longer than 5s"):
        hf.render(proj, tmp_path / "v.mp4", timeout_s=5, run=slow, log=lambda *_: None)
    monkeypatch.setenv("HH_HYPERFRAMES", str(tmp_path / "missing.cmd"))
    assert not hf.available()
    with pytest.raises(hf.RenderError, match="not installed"):
        hf.render(proj, tmp_path / "v.mp4", log=lambda *_: None)


@pytest.mark.skipif(os.environ.get("HH_LIVE_HF") != "1" or not hf.available(),
                    reason="live render: set HH_LIVE_HF=1 on a PC with HyperFrames installed")
def test_live_smoke_render(tmp_path):
    out = hf.smoke(tmp_path / "smoke", log=lambda *_: None)
    assert out.exists() and out.stat().st_size > 1024
