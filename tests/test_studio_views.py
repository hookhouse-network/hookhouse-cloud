"""Dashboard review player, card/calendar views and KV video previews (owner 19 Nov)."""
import json
from datetime import datetime, timedelta

from engine import dashboard_studio as st
from engine import pc_fallback as pf


class FakeKV:
    def __init__(self):
        self.d, self.b = {}, {}

    def put(self, k, v, ttl=None):
        self.d[k] = v

    def put_bytes(self, k, v, ttl=None):
        self.b[k] = v

    def delete(self, k):
        self.d.pop(k, None)
        self.b.pop(k, None)


def _item(tmp_path, iid, status, kind="short", size=1000):
    out = tmp_path / iid
    out.mkdir()
    (out / "video.mp4").write_bytes(b"x" * size)
    when = (datetime.now(st.IST) + timedelta(days=1)).replace(microsecond=0).isoformat()
    return {"id": iid, "channel": "c1", "status": status, "kind": kind, "out_dir": str(out), "file": "video.mp4",
            "publish_at": when}


def test_previews_chunked_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PREVIEW_FILE", tmp_path / "pv.json")
    monkeypatch.setattr(pf, "PREVIEW_CHUNK", 400)
    a = _item(tmp_path, "a", "made")
    items = [("w", a)]
    monkeypatch.setattr("engine.autopilot.items", lambda *x: items)
    monkeypatch.setattr(pf, "make_preview", lambda it: __import__("pathlib").Path(it["out_dir"]) / "video.mp4")
    kv = FakeKV()
    assert pf.push_previews(kv, log=lambda m: None) == 1
    assert sorted(kv.b) == ["pv:a:0", "pv:a:1", "pv:a:2"]
    assert kv.d["pv:a:meta"] == {"size": 1000, "chunks": 3, "chunk": 400}
    assert pf.push_previews(kv, log=lambda m: None) == 0          # unchanged file: not sent again
    a["status"] = "posted"
    pf.push_previews(kv, log=lambda m: None)
    assert not kv.b and "pv:a:meta" not in kv.d and pf.previews() == {}


def test_content_card_views_and_telegram_buttons(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PREVIEW_FILE", tmp_path / "pv.json")
    made = _item(tmp_path, "m1", "made")
    plan = _item(tmp_path, "p1", "planned")
    (tmp_path / "pv.json").write_text(json.dumps({"m1": {"sig": "s", "size": 1, "chunks": 1,
                                                         "at": __import__("time").time()}}))
    monkeypatch.setattr(st, "_details", lambda it: "Title: x")
    html = st.content_card({"id": "c1"}, {"items": [made, plan]}, poster=lambda f, n: "data:x")
    assert "data-v=cards" in html and "data-v=cal" in html and "data-v=list" in html
    assert "✅ Approve &amp; post" in html or "✅ Approve & post" in html
    assert "✏️ Change" in html and "❌ Reject" in html
    assert "data-pv='m1'" in html                                  # player for the ready video
    assert "hhOpen('m1')" in html and "1 waiting for you" in html
    assert "🎬 Make now" in html


def test_lessons_explain_empty_channel(monkeypatch):
    monkeypatch.setattr(st, "ROOT", __import__("pathlib").Path("/nonexistent"))
    out = st.lessons_html("zz", {"items": []})
    assert "No video has gone public" in out
