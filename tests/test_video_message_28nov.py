"""28 Nov (P10): one Telegram message per video. 'Posted' / 'Nothing posted' edit the auto-approval message (its Stop
button ends) instead of sending a new one; with no message to edit, a new alert is sent as before."""
from engine import autopilot
from engine import telegram_bot as tb


def test_posted_edits_the_videos_message(monkeypatch, tmp_path):
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    calls, sent = [], []
    monkeypatch.setattr(tb, "api", lambda method, **kw: calls.append((method, kw)) or {"ok": True})
    monkeypatch.setattr(tb, "_chat", lambda: "42")
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    autopilot.video_message("v1", "🤖 Auto-approved: Brain Snack", {"message_id": 7})
    assert autopilot.video_update("v1", "📤 Posted Brain Snack")
    method, kw = calls[-1]
    assert method == "editMessageText" and kw["message_id"] == 7 and kw["reply_markup"] == {"inline_keyboard": []}
    assert kw["text"].startswith("🤖 Auto-approved") and kw["text"].endswith("📤 Posted Brain Snack")
    assert not sent
    assert autopilot.video_update("v1", "extra line")                        # later news appends again
    assert "📤 Posted Brain Snack\n\nextra line" in calls[-1][1]["text"]


def test_no_message_or_a_failed_edit_sends_a_new_alert(monkeypatch, tmp_path):
    monkeypatch.setattr(autopilot, "STATE", tmp_path / "autopilot.json")
    sent = []
    monkeypatch.setattr(tb, "notify", lambda t: sent.append(t) or True)
    monkeypatch.setattr(tb, "_chat", lambda: "42")
    assert not autopilot.video_update("unknown", "📤 Posted X") and sent == ["📤 Posted X"]

    def broken(method, **kw):
        raise RuntimeError("message to edit not found")
    monkeypatch.setattr(tb, "api", broken)
    autopilot.video_message("v2", "approved", {"message_id": 9})
    assert not autopilot.video_update("v2", "📤 Posted Y") and sent[-1] == "📤 Posted Y"
