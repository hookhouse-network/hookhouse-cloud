"""24 Nov: Wild Instinct (no Instagram or Threads account yet) logged "Instagram gave no video link to pass on to
Threads" as a HIGH heal item at every live post. A channel without a Threads account only plans the Threads post, the
way Instagram and Facebook already do for unconnected channels; a connected channel keeps the retry-able error."""
import json

from engine import threads


def _video(tmp_path):
    out = tmp_path / "v"
    out.mkdir()
    (out / "video.mp4").write_bytes(b"x")
    (out / "upload.json").write_text(json.dumps({"title": "The wolf that came back", "format": "short",
                                                 "description": "A pack returns.", "hashtags": ["#wolves"]}))
    return out


def _unconnected_reel(channel_id, video, caption, **k):
    import engine.publish as pub
    a = pub.Action("instagram", channel_id, k.get("item_id", ""), "publish Reel")
    a.details["dry_run"] = True
    return a


def test_a_channel_without_a_threads_account_plans_the_post_instead_of_an_error(tmp_path, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(pub, "instagram_reel", _unconnected_reel)
    monkeypatch.setattr(pub, "_duration", lambda v: 30.0)
    monkeypatch.setattr(threads, "creds", lambda cid: None)
    asked = []
    monkeypatch.setattr(threads, "ig_video_url", lambda *a, **k: asked.append(a) or None)
    it = {"id": "i1", "channel": "wild_instinct", "channel_name": "W", "out_dir": str(_video(tmp_path)),
          "publish_at": "", "youtube_id": "yt1"}
    acts = pub.upload_item(it, dry_run=False, platforms=("instagram", "threads"))
    th = [a for a in acts if a.platform == "threads"][0]
    assert th.details.get("dry_run") and not th.done
    assert not (th.result or {}).get("error")
    assert not asked                                     # Instagram is never asked for a link it cannot have
    logged = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not any("pass on to Threads" in json.dumps(x) for x in logged)


def test_a_connected_channel_without_a_reel_link_still_reports_the_error(tmp_path, monkeypatch):
    import engine.publish as pub
    monkeypatch.setattr(pub, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(pub, "instagram_reel", lambda *a, **k: pub.Action("instagram", "x", "i1", "publish Reel"))
    monkeypatch.setattr(pub, "_duration", lambda v: 30.0)
    monkeypatch.setattr(threads, "creds", lambda cid: {"user_id": "u1", "access_token": "tok"})
    monkeypatch.setattr(pub, "share_link", lambda f: None)
    it = {"id": "i1", "channel": "unsolved_after_dark", "channel_name": "U", "out_dir": str(_video(tmp_path)),
          "publish_at": "", "youtube_id": "yt1"}
    acts = pub.upload_item(it, dry_run=False, platforms=("instagram", "threads"))
    th = [a for a in acts if a.platform == "threads"][0]
    assert not th.done and not th.details.get("dry_run") and "pass on to Threads" in th.result.get("error", "")
