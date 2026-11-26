"""27 Nov (P4 adapter contract tests): Facebook Reels had no test. The contract: start -> upload the bytes -> finish
with video_state PUBLISHED; refusals at start or finish are errors with Meta's reason; no Page = a dry run."""
import json

import pytest

from engine import publish


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class Session:
    def __init__(self, start, finish):
        self.start, self.finish, self.calls = start, finish, []

    def post(self, url, data=None, headers=None, timeout=None):
        phase = (data or {}).get("upload_phase") if isinstance(data, dict) else "bytes"
        self.calls.append((url.split("/")[-1] if phase != "bytes" else "upload", phase))
        if phase == "start":
            return Resp(self.start)
        if phase == "finish":
            return Resp(self.finish)
        return Resp({"success": True})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(publish, "meta_creds", lambda cid: {"page_id": "P1", "page_token": "T", "access_token": "A"})
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 1000)
    return v


def test_the_three_step_reel_upload(env):
    s = Session({"video_id": "V9"}, {"success": True})
    a = publish.facebook_reel("brain_snack", env, "desc", session=s, dry_run=False, item_id="i1")
    assert a.done and a.result["video_id"] == "V9"
    assert [c[1] for c in s.calls] == ["start", "bytes", "finish"]


def test_refusals_carry_metas_reason(env):
    a = publish.facebook_reel("brain_snack", env, "d", session=Session({"error": {"message": "no permission"}}, {}),
                              dry_run=False, item_id="i1")
    assert not a.done and "no permission" in a.result["error"]
    b = publish.facebook_reel("brain_snack", env, "d", session=Session({"video_id": "V1"},
                              {"error": {"error_user_msg": "too long"}}), dry_run=False, item_id="i1")
    assert not b.done and "too long" in b.result["error"] and b.result["video_id"] == "V1"


def test_no_page_is_a_dry_run(env, monkeypatch):
    monkeypatch.setattr(publish, "meta_creds", lambda cid: None)
    a = publish.facebook_reel("brain_snack", env, "d", session=Session({}, {}), dry_run=False, item_id="i1")
    assert a.details.get("dry_run") and not a.done
    rows = [json.loads(x) for x in publish.LOG.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["details"]["dry_run"] is True
