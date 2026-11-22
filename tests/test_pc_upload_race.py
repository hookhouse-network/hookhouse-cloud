"""22 Nov 09:26: the PC made the Itihaas 12:30 video again three minutes after uploading it. The merging cloud tick
had deleted the claim but saves the plan only at its end, so the PC's fresh copy still showed the video unmade and
unclaimed. The PC now remembers its uploads and skips a video until its plan copy shows the merged make."""
import inspect
import json
import time

import pytest

from engine.cloud import media, pc_outbox, runner


@pytest.fixture
def outbox(monkeypatch, tmp_path):
    monkeypatch.setattr(pc_outbox, "PENDING", tmp_path / "pending")
    monkeypatch.setattr(pc_outbox, "UPLOADED", tmp_path / "uploaded.json")
    monkeypatch.setattr(media, "upload", lambda store, item_id, folder: None)

    class Store:
        def __init__(self):
            self.files = {}

        def put(self, tag, name, data, content_type=""):
            self.files[name] = data
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "video.mp4").write_bytes(b"x")
    return Store(), folder


def test_an_uploaded_video_waits_for_the_merge_in_the_plan_copy(outbox):
    store, folder = outbox
    made_at = time.time() - 60
    pc_outbox.add("v1", folder, {"id": "v1", "made_at": made_at})
    assert pc_outbox.flush(store, log=lambda *a: None) == 1 and "done-v1.json" in store.files
    assert json.loads(pc_outbox.UPLOADED.read_text())["v1"]["made_at"] == pytest.approx(made_at)
    assert pc_outbox.awaiting_merge({"id": "v1", "status": "planned"})                    # stale copy: skip
    assert pc_outbox.awaiting_merge({"id": "v1", "status": "failed", "made_at": made_at - 3600})   # an older make
    assert not pc_outbox.awaiting_merge({"id": "v1", "status": "redo", "made_at": made_at})  # merged, then redo
    assert not pc_outbox.awaiting_merge({"id": "v2", "status": "planned"})                # never uploaded here


def test_a_merge_that_never_shows_up_lets_the_pc_make_it_again(outbox):
    pc_outbox._remember_upload("v1", time.time() - 8 * 3600, time.time() - 7 * 3600)
    assert not pc_outbox.awaiting_merge({"id": "v1", "status": "planned"})


def test_old_upload_records_are_dropped(outbox):
    pc_outbox._remember_upload("old", 1.0, time.time() - 3 * 86400)
    pc_outbox._remember_upload("new", time.time(), time.time())
    assert set(pc_outbox._uploads()) == {"new"}


def test_the_helper_skips_videos_awaiting_their_merge():
    assert "pc_outbox.awaiting_merge(it)" in inspect.getsource(runner.helper)
