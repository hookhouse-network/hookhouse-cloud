"""27 Nov (P2b Telegram 2.0): 📺 Channels -> one channel's menu -> 💡 Pick a topic in demand -> [Make n]; every
button path against a fake Telegram API."""
from engine import autopilot, picker
from engine import telegram_bot as tb


def _cb(data):
    return {"callback_query": {"id": "1", "data": data, "message": {"chat": {"id": 42}, "message_id": 7}}}


def test_the_channel_menu_and_pick_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(tb, "STATE", tmp_path / "state.json")
    sent = []

    def fake_api(method, files=None, http_timeout=30, **p):
        if method == "sendMessage":
            sent.append((p["text"], p.get("reply_markup")))
            return {"message_id": 7}
        return True
    monkeypatch.setattr(tb, "api", fake_api)
    monkeypatch.setattr(autopilot, "items", lambda back=3, ahead=9: [("s", {
        "id": "1128_0500_brain_snack_short", "channel": "brain_snack", "status": "planned",
        "publish_at": "2026-11-28T05:00:00+05:30", "topic": "Why ice floats"})])
    monkeypatch.setattr(picker, "suggest", lambda cid, n=5, brain=None, log=print: [
        {"topic": "Why cats purr", "demand": "hot: 40k views/day"}, {"topic": "Glass is not a liquid", "demand": ""}])
    made = []
    monkeypatch.setattr(picker, "pick_topic", lambda topic, cid, demand="", log=print: made.append((topic, cid)) or
                        f"Picked: {topic} for {cid}")

    tb.handle({"message": {"chat": {"id": 42}, "text": "📺 Channels"}})
    text, kb = sent[-1]
    assert text.startswith("📺 Which channel?")
    assert any(b["callback_data"] == "chn:brain_snack" for row in kb["inline_keyboard"] for b in row)

    tb.handle(_cb("chn:brain_snack"))
    text, kb = sent[-1]
    assert "Brain Snack" in text and "Why ice floats" in text
    assert kb["inline_keyboard"][0][0]["callback_data"] == "chp:brain_snack"

    tb.handle(_cb("chp:brain_snack"))
    text, kb = sent[-1]
    assert "1. Why cats purr" in text and [r[0]["callback_data"] for r in kb["inline_keyboard"]] == ["chm:0", "chm:1"]

    tb.handle(_cb("chm:0"))
    assert made == [("Why cats purr", "brain_snack")] and sent[-1][0] == "Picked: Why cats purr for brain_snack"
    tb.handle(_cb("chm:9"))
    assert "expired" in sent[-1][0]


def test_the_morning_health_digest_combines_health_and_owner_tasks(monkeypatch):
    monkeypatch.setattr(tb, "health_text", lambda: "All good: 6 posted today")
    monkeypatch.setattr(tb, "tasks_text", lambda: "Connect PayPal in Payhip")
    d = tb.health_digest()
    assert d.startswith("🩺 Morning health check") and "6 posted today" in d and "Connect PayPal" in d
    monkeypatch.setattr(tb, "tasks_text", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert "could not read" in tb.health_digest() and "6 posted today" in tb.health_digest()
