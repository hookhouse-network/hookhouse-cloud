"""Own training set: scripts recorded at make time, joined with their numbers later (owner 19 Nov)."""
import json

from engine import analytics, training_data as td


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(td, "DIR", tmp_path / "training")
    monkeypatch.setattr(td, "SCRIPTS", tmp_path / "training" / "scripts.jsonl")
    monkeypatch.setattr(td, "EXAMPLES", tmp_path / "training" / "examples.jsonl")


def _video(tmp_path, iid, title):
    out = tmp_path / iid
    out.mkdir()
    (out / "script.json").write_text(json.dumps({"title": title, "hook_text": "Wait for it", "hook_type": "outcome_first",
                                                 "beats": [{"narration": "He jumped first."}, {"narration": "Then the rope."}]}))
    (out / "upload.json").write_text(json.dumps({"title": title}))
    return {"id": iid, "channel": "c1", "kind": "short", "out_dir": str(out), "topic": "t", "feeling": "shocking"}


def test_record_and_build_with_scores(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert td.record(_video(tmp_path, "a", "Big win"))["hook_type"] == "outcome_first"
    td.record(_video(tmp_path, "b", "Small win"))
    td.record({"id": "x", "out_dir": str(tmp_path / "missing")})          # nothing to keep: no crash, no row
    db = tmp_path / "a.db"
    conn = analytics.connect(db)
    base = {"channel": "c1", "platform": "youtube", "format": "short", "posted_at": 1.0}
    analytics.record(conn, **base, item_id="a", video_id="A", hours_after=72, views=1000, likes=40, engaged_views=800)
    analytics.record(conn, **base, item_id="b", video_id="B", hours_after=72, views=100, likes=1, engaged_views=40)
    analytics.record(conn, **base, item_id="b", video_id="B", hours_after=2, views=5, likes=0)      # too early
    conn.commit()
    conn.close()
    assert td.build(db) == 2
    rows = {r["item_id"]: r for r in map(json.loads, td.EXAMPLES.read_text(encoding="utf-8").splitlines())}
    assert rows["a"]["stayed_pct"] == 80.0 and rows["a"]["like_rate"] == 4.0
    assert rows["a"]["score"] > rows["b"]["score"]
    assert rows["a"]["opening"] == ["He jumped first.", "Then the rope."]
    st = td.status()
    assert st == {"scripts": 2, "labelled": 2, "ready_at": td.READY_AT, "ready": False}


def test_remake_replaces_first_record(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    td.record(_video(tmp_path, "a", "First"))
    (tmp_path / "a" / "upload.json").write_text(json.dumps({"title": "Second"}))
    td.record({"id": "a", "channel": "c1", "out_dir": str(tmp_path / "a")})
    assert td._scripts()["a"]["title"] == "Second"
