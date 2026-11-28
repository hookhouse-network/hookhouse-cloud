"""27 Nov (P2b Control Center v1): every screen renders, read-only, escaped, and degraded (not crashed) when the
shared queue is unreachable."""
import pytest

pytest.importorskip("starlette")                  # the Control Center is PC-only; CI installs the cloud requirements
from starlette.testclient import TestClient  # noqa: E402

from engine import autopilot  # noqa: E402
from engine.console import app as console  # noqa: E402


def test_every_screen_renders_and_degrades(monkeypatch):
    monkeypatch.setattr(autopilot, "items", lambda back=3, ahead=9: [("s", {
        "id": "1127_0500_x_short", "channel": "x", "channel_name": "<b>X</b>", "kind": "short", "status": "made",
        "publish_at": "2026-11-27T05:00:00+05:30", "topic": "t"})])
    monkeypatch.setattr(autopilot, "gate_held", lambda: {"1127_0500_x_short": {"problems": ["potential: hook 5"],
                                                                                "channel": "X", "at": 1}})
    monkeypatch.setattr(console, "_sched", lambda: ({}, "shared queue unreachable (ConnectionError)"))
    monkeypatch.setattr(console, "_dash", lambda: "https://example.invalid/d")
    c = TestClient(console.app)
    home = c.get("/")
    assert home.status_code == 200 and "Degraded: shared queue unreachable" in home.text and "Waiting approval" in home.text
    pipe = c.get("/pipeline")
    assert pipe.status_code == 200 and "&lt;b&gt;X&lt;/b&gt;" in pipe.text and "<b>X</b>" not in pipe.text   # escaped
    assert "potential: hook 5" in c.get("/gates").text
    assert c.get("/queue").status_code == 200
    assert "Approve / act (cloud)" in home.text                     # actions open the cloud dashboard


def test_pause_and_resume_from_the_workers_screen(monkeypatch, tmp_path):
    from engine.cloud import runner
    monkeypatch.setattr(runner, "PAUSE_FILE", tmp_path / "paused.txt")
    monkeypatch.setattr(console, "_sched", lambda: ({"online": []}, ""))
    monkeypatch.setattr(console, "_dash", lambda: "")
    c = TestClient(console.app)
    assert "Pause video making" in c.get("/workers").text
    assert c.post("/workers/pause", headers={"origin": "https://evil.example"}).status_code == 403   # other sites refused
    r = c.post("/workers/pause", headers={"origin": "http://127.0.0.1:8765"}, follow_redirects=False)
    assert r.status_code == 303 and (tmp_path / "paused.txt").exists()
    assert "Resume video making" in c.get("/workers").text
    c.post("/workers/resume", headers={"origin": "http://127.0.0.1:8765"})
    assert not (tmp_path / "paused.txt").exists()


def test_the_budgets_screen(monkeypatch):
    from engine import budgets
    monkeypatch.setattr(budgets, "summary", lambda: {"ai": [{"provider": "groq", "calls": 7, "errors": 0,
                                                              "quota_hits": 0}],
                                                     "pictures": [{"source": "cloudflare", "open": False,
                                                                   "until": "28 Nov 05:30"}],
                                                     "local": {"used": 93, "cap": 120, "why_not": "the PC is in use"}})
    monkeypatch.setattr(console, "_dash", lambda: "")
    t = TestClient(console.app).get("/budgets").text
    assert "groq" in t and "used up until 28 Nov 05:30" in t and "93 / 120" in t and "the PC is in use" in t


def test_money_and_calendar_screens_and_no_internal_ids(monkeypatch):
    from engine import operator_brief
    monkeypatch.setattr(operator_brief, "earnings", lambda: (1500.0, 2.25))
    monkeypatch.setattr(console, "_board", lambda days=7: [{"channel": "Brain Snack", "posts": 16, "views": 21361.0}])
    monkeypatch.setattr(console, "_dash", lambda: "")
    monkeypatch.setattr(autopilot, "items", lambda back=3, ahead=9: [("s", {
        "id": "1128_0500_x_short", "channel": "x", "channel_name": "Cosmos", "kind": "short", "status": "made",
        "publish_at": "2026-11-28T05:00:00+05:30", "topic": "t"})])
    monkeypatch.setattr(autopilot, "gate_held", lambda: {"1128_0500_x_short": {"problems": ["quality 79"],
                                                                                "channel": "Cosmos", "at": 1}})
    c = TestClient(console.app)
    m = c.get("/money").text
    assert "Rs 1,500" in m and "$2.25" in m and "Brain Snack" in m and "21,361" in m
    cal = c.get("/calendar").text
    assert "Sat 28 Nov" in cal and "waiting approval" in cal and "Cosmos" in cal
    g = c.get("/gates").text
    assert "28 Nov 05:00 Short" in g and "1128_0500_x_short" not in g
    assert console.slot_label("weird") == "a video"


def test_help_screen_shows_the_guide_safely(monkeypatch):
    monkeypatch.setattr(console, "_dash", lambda: "")
    h = TestClient(console.app).get("/help").text
    assert "<h3>Start it</h3>" in h and "<th>Screen</th>" in h and "<b>Money</b>" in h
    out = console.md_html("- a **b** <script>x</script>\n  more\n\n| A | B |\n|---|---|\n| 1 | 2 |")
    assert "&lt;script&gt;" in out and "<script>" not in out and "<li>a <b>b</b>" in out and "more</li>" in out
    assert "<td>1</td>" in out
