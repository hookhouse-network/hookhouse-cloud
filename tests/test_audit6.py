"""Sixth pass (12 Nov): peak limiter after loudness, hook line in approvals, Instagram caption limits."""
import json

from engine import autopilot, publish


def test_every_loudness_step_ends_in_a_peak_limiter():
    from pathlib import Path
    for f in ("engine/story.py", "engine/snack/encode.py", "engine/clipv3.py"):
        src = Path(f).read_text(encoding="utf-8")
        assert "TP=-1.5" in src and "alimiter=limit=0.83" in src, f


def test_approval_shows_the_opening_line(tmp_path):
    (tmp_path / "script.json").write_text(json.dumps({"beats": [{"narration": "The ship wasn't sinking."}]}))
    assert autopilot._opening_line({"out_dir": str(tmp_path)}) == "The ship wasn't sinking."
    (tmp_path / "script.json").unlink()
    (tmp_path / "clips.json").write_text(json.dumps([{"file": "clip_01.mp4", "hook_options": ["He said WHAT?"]}]))
    assert autopilot._opening_line({"out_dir": str(tmp_path), "file": "clip_01.mp4"}) == "He said WHAT?"


def test_instagram_caption_is_trimmed_to_platform_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "meta_creds", lambda c: {"ig_user_id": "1", "access_token": "t"})
    v = tmp_path / "r.mp4"
    v.write_bytes(b"x")
    sent = {}

    class R:
        def __init__(self, d):
            self.d, self.status_code = d, 200

        def json(self):
            return self.d

    class S:
        def get(self, url, **k):
            return R({"data": [{"quota_usage": 0}]} if "limit" in url else {"status_code": "FINISHED"})

        def post(self, url, data=None, **k):
            if url.endswith("/media"):
                sent["caption"] = data["caption"]
                return R({"id": "C"})
            return R({"id": "M"})
    cap = "Story " + " ".join(f"#tag{i}" for i in range(40)) + " " + "x" * 3000
    publish.instagram_reel("x", v, cap, session=S(), dry_run=False, poll_s=0)
    assert len(sent["caption"]) <= 2200 and sent["caption"].count("#") <= 30
