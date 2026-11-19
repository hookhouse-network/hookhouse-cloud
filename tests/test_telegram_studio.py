"""19 Nov (owner: "make the Telegram process simple, clear, fast"): the menu button opens the Studio in Telegram."""
from engine import telegram_bot as tb


def test_studio_button_is_set_for_the_owner_chat_only(monkeypatch):
    calls = []
    monkeypatch.setattr(tb, "_chat", lambda: "42")
    monkeypatch.setattr(tb, "api", lambda method, **p: calls.append((method, p)) or True)
    assert tb.studio_button("https://bot.example.workers.dev/d?k=x" * 1)
    method, p = calls[0]
    assert method == "setChatMenuButton" and p["chat_id"] == "42"
    assert p["menu_button"]["type"] == "web_app" and p["menu_button"]["web_app"]["url"].startswith("https://")


def test_no_button_without_a_safe_link(monkeypatch):
    monkeypatch.setattr(tb, "_chat", lambda: "42")
    monkeypatch.setattr(tb, "api", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    assert not tb.studio_button("")
    assert not tb.studio_button("http://plain.example/d")      # Telegram web apps need https


def test_help_points_to_the_studio():
    assert "🎬 Studio" in tb.HELP
    assert "🎬 Studio" in open("cloud/worker/worker.js", encoding="utf-8").read()
