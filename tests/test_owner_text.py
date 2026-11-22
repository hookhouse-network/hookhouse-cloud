"""22 Nov: the owner's typed answers in Telegram (to the questions Claude asks there) were dropped by the cloud run
after the Worker's "working on it"; they are now saved (owner_said.jsonl + ledger event) and acknowledged honestly."""
import json

from engine import telegram_bot as tb
from engine.core import ledger


def _setup(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(tb, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(tb, "SAID", tmp_path / "owner_said.jsonl")
    monkeypatch.setattr(tb, "LOG_FILE", tmp_path / "bot.log")

    def fake_api(method, files=None, http_timeout=30, **p):
        if method == "sendMessage":
            sent.append(p["text"])
        return {"message_id": 1}

    monkeypatch.setattr(tb, "api", fake_api)
    return sent


def _msg(text, chat=42):
    return {"message": {"chat": {"id": chat}, "text": text}}


def test_owner_answer_is_saved_and_acknowledged(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path)
    tb.handle(_msg("my approvals post"))
    rows = tb.owner_said()
    assert [r["text"] for r in rows] == ["my approvals post"]
    assert "Saved for Claude" in sent[-1] and "my approvals post" in sent[-1]
    ev = ledger.default().events("owner_text")
    assert ev and ev[-1]["data"]["text"] == "my approvals post"


def test_commands_menu_and_strangers_are_not_saved(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(tb, "status_text", lambda: "today: fine")
    tb.handle(_msg("/status"))
    tb.handle(_msg("📊 Today"))                       # a tap on the bottom menu is a command, not a message
    tb.handle(_msg("run them", chat=99))              # only the owner's chat counts
    tb.handle(_msg("/nonsense"))
    assert tb.owner_said() == []
    assert sent[:2] == ["today: fine", "today: fine"] and "I don't know that command" in sent[-1]
    assert len(sent) == 3


def test_awaited_change_still_goes_to_the_video(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path)
    import time
    tb._save({"awaiting_change": {"tok": "abc123", "at": time.time()}})
    got = []
    monkeypatch.setattr("engine.autopilot.decide", lambda tok, act, text: got.append((tok, act, text)) or "ok, remaking")
    tb.handle(_msg("make the hook scarier"))
    assert got == [("abc123", "change", "make the hook scarier")]
    assert tb.owner_said() == [] and sent[-1] == "ok, remaking"


def test_reader_keeps_order_skips_damage_and_trims(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(tb, "SAID_KEEP", 3)
    for i, t in enumerate(["a", "b", "c", "d"]):
        tb.note_owner_text(t, at=1000.0 + i)
    with tb.SAID.open("a", encoding="utf-8") as f:
        f.write("{broken\n")
    assert [r["text"] for r in tb.owner_said()] == ["b", "c", "d"]   # the oldest one trimmed, the damaged line skipped
    assert [r["text"] for r in tb.owner_said(since=1002.0)] == ["c", "d"]
    long_reply = tb.note_owner_text("x" * 500, at=2000.0)
    assert "..." in long_reply and len(long_reply) < 400
    assert json.loads(tb.SAID.read_text(encoding="utf-8").splitlines()[-1])["text"] == "x" * 500
