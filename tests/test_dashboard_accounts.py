"""Dashboard Accounts & links grid (owner 19 Nov)."""
import json

from engine import dashboard_accounts as da


def test_cells_states(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "SECRETS", tmp_path)
    (tmp_path / "youtube_c.json").write_text("{}")
    (tmp_path / "meta_c.json").write_text(json.dumps({"page_id": "123", "ig_user_id": "9"}))
    c = da.cells("c", {"youtube": "@chan", "instagram": "chanig"})
    assert c["youtube"][0] == "good" and c["youtube"][2].endswith("/@chan")
    assert c["instagram"] == ("good", "@chanig", "https://www.instagram.com/chanig")
    assert c["facebook"][2] == "https://www.facebook.com/123"
    assert c["threads"][0] == "todo" and c["pinterest"][0] == "todo"


def test_planned_instagram_never_linked(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "SECRETS", tmp_path)
    c = da.cells("x", {"youtube": "@x", "instagram": "maybe_a_stranger"})
    assert c["instagram"] == ("todo", "to create", "")              # a planned handle is not a link
    c = da.cells("x", {"instagram": "ours", "instagram_live": True})
    assert c["instagram"][0] == "warn" and c["instagram"][2].endswith("/ours")
