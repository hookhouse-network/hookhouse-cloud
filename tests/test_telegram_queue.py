"""20 Nov (owner): "telegram must have a button for waiting for approval that gives the list of videos that need my
approval" + approve / reject / change on each."""
import json
from datetime import datetime, timedelta

from engine import autopilot, telegram_bot as tb, weekly


def _plan(tmp_path, monkeypatch, items):
    monkeypatch.setattr(weekly, "WEEKS_DIR", tmp_path / "weeks")
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    start = datetime.now(weekly._zone()).date().isoformat()
    d = tmp_path / "weeks" / start
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"start": start, "items": items}), encoding="utf-8")
    return start


def _item(i, status, hours, channel="brain_snack", made_at=100.0, **kw):
    when = (datetime.now(weekly._zone()) + timedelta(hours=hours)).isoformat()
    return dict({"id": f"it{i}", "channel": channel, "channel_name": channel.replace("_", " ").title(),
                 "kind": "short", "publish_at": when, "status": status, "topic": f"Topic {i}", "made_at": made_at}, **kw)


def test_cards_list_every_waiting_video_soonest_first_with_three_buttons(tmp_path, monkeypatch):
    items = [_item(1, "made", 50), _item(2, "made", 5), _item(3, "approved", 3), _item(4, "made", 100),
             _item(5, "posted", -2)]
    _plan(tmp_path, monkeypatch, items)
    autopilot._save({"asked": {"it1": 200, "it2": 200, "it4": 200}})       # all three were offered (gates passed)
    q = tb.queue_cards()
    assert q["count"] == 3 and q["checking"] == 0
    assert [c["text"].split("\n")[1] for c in q["cards"]] == ["Topic 2", "Topic 1", "Topic 4"]   # beyond 2 days too
    kb = q["cards"][0]["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in kb] == ["✅ Approve & post", "✏️ Change", "❌ Reject"]
    assert [b["callback_data"][:3] for b in kb] == ["ap:", "ch:", "rj:"]
    assert q["header_kb"]["inline_keyboard"][0][0]["callback_data"] == "aa:all"
    assert "3 video(s) need your OK" in q["header"]


def test_videos_not_through_the_gates_get_no_buttons(tmp_path, monkeypatch):
    _plan(tmp_path, monkeypatch, [_item(1, "made", 5), _item(2, "made", 6, made_at=500.0)])
    autopilot._save({"asked": {"it1": 200, "it2": 200}})                   # it2 was remade after it was offered
    q = tb.queue_cards()
    assert q["count"] == 1 and q["checking"] == 1 and "1 more being checked" in q["header"]
    assert q["header_kb"] is None                                          # approve-all only for 2+


def test_nothing_waiting(tmp_path, monkeypatch):
    _plan(tmp_path, monkeypatch, [_item(1, "approved", 5)])
    q = tb.queue_cards()
    assert q["cards"] == [] and "Nothing is waiting" in q["header"]


def test_the_worker_answers_at_once_and_marks_taps():
    js = open("cloud/worker/worker.js", encoding="utf-8").read()
    assert "snap.queue" in js and "dec:${c.tok}" in js                     # cards from the snapshot, decided left out
    assert "editMessageReplyMarkup" in js and "✅ Approved: posts at its slot" in js
    src = open("engine/cloud/runner.py", encoding="utf-8").read()
    assert "queue_cards()" in src and '"queue": queue' in src


# ---------------------------------------------------------------- Studio inbox (20 Nov redesign)
def test_studio_inbox_lists_waiting_videos_with_the_three_buttons(tmp_path):
    from engine import dashboard_studio as ds
    soon = (datetime.now(weekly._zone()) + timedelta(hours=5)).isoformat()
    later = (datetime.now(weekly._zone()) + timedelta(hours=30)).isoformat()
    items = [{"id": "b", "channel": "c", "status": "made", "publish_at": later, "kind": "short", "topic": "Later one",
              "out_dir": str(tmp_path / "none")},
             {"id": "a", "channel": "c", "status": "made", "publish_at": soon, "kind": "short", "topic": "Soon one",
              "out_dir": str(tmp_path / "none")},
             {"id": "z", "channel": "c", "status": "approved", "publish_at": soon, "kind": "short", "topic": "Done"}]
    html = ds.inbox_card({"items": items})
    assert html.index("Soon one") < html.index("Later one") and "Done" not in html
    for b in ("✅ Approve & post", "✏️ Change", "❌ Reject"):
        assert html.count(f">{b}</button>") == 2     # shown even though the files are not on this machine
    assert "Upload now" not in html                   # that one needs the file
    assert "id='ib-a'" in html and "id='sc-a'" not in html
    assert "GitHub is down" not in html


def test_studio_inbox_when_nothing_waits():
    from engine import dashboard_studio as ds
    assert "Nothing is waiting" in ds.inbox_card({"items": []})


def test_studio_taps_say_the_cloud_does_it():
    from engine import dashboard_studio as ds
    assert "the PC is off" not in ds.JS and "done within a few minutes" in ds.JS
