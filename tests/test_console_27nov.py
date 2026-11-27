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
