"""25 Nov: the 3 GTA clips were sent back for a remake, but every Dasgasd3m source was marked used (their own too):
the paused story channel saw no clip slot and the PC made nothing for hours. A clip's remake cuts its own footage."""
from engine import weekly

CH = {"id": "stream_clips", "type": "story", "clips_first": True}
SRC = "asset:src-dasgasd3m-x-ruckus-gta-6-kick-EHA918XBYJ9R.mp4"


def test_a_clip_remake_is_a_clip_slot_with_its_own_footage(monkeypatch, tmp_path):
    f = tmp_path / "clip_sources.txt"
    f.write_text(f"{SRC} dasgasd3m-x-ruckus-gta-6\n", encoding="utf-8")
    monkeypatch.setattr(weekly, "CLIP_SOURCES", f)
    monkeypatch.setattr(weekly, "clip_state", lambda: {"pool": {}, "used": [SRC]})   # everything used
    redo = {"id": "1121_0100_stream_clips_short", "kind": "short", "status": "redo", "clip_source": SRC}
    assert weekly._remake_source(redo) == {"source": SRC, "campaign": "dasgasd3m-x-ruckus-gta-6", "channel": None}
    assert weekly.clip_slot(CH, redo) is True
    assert weekly.clip_slot(CH, dict(redo, status="planned")) is False       # an ordinary slot still needs new footage
    assert weekly._remake_source(dict(redo, clip_source=None)) is None


def test_the_remake_cuts_its_own_source_not_a_spare_clip(monkeypatch, tmp_path):
    f = tmp_path / "clip_sources.txt"
    f.write_text(f"{SRC} dasgasd3m-x-ruckus-gta-6\n", encoding="utf-8")
    monkeypatch.setattr(weekly, "CLIP_SOURCES", f)
    state = {"pool": {"stream_clips": [{"out_dir": "x", "file": "spare.mp4", "at": 9e12}]}, "used": [SRC]}
    monkeypatch.setattr(weekly, "clip_state", lambda: state)
    cut = []

    class Stop(Exception):
        pass

    from engine import clips, db
    monkeypatch.setattr(db, "connect", lambda: None)
    monkeypatch.setattr(db, "get_campaign", lambda c, cid: {"id": cid})
    monkeypatch.setattr(clips, "make_clips", lambda brain, src, ch, **k: cut.append(src) or (_ for _ in ()).throw(Stop()))
    monkeypatch.setattr(weekly, "_count_clip_failure", lambda s: 0)
    item = {"id": "1121_0100_stream_clips_short", "kind": "short", "status": "redo", "clip_source": SRC}
    try:
        weekly._make_clip({}, item, None, CH, None, print)
    except Stop:
        pass
    assert cut == [SRC]
