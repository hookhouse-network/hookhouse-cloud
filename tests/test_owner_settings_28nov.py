"""28 Nov (P10): owner switches changed safely in three taps. Only listed switches and values; the choice merges
into the config the cloud reads; anything else is refused and changes nothing."""
import pytest

from engine import owner_settings as os_


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(os_, "STATE", tmp_path / "owner_settings.json")
    return tmp_path / "owner_settings.json"


def test_a_choice_merges_into_the_right_config(state):
    cfg = {"data_story": "on", "local_pictures": {"enabled": True, "max_day": 120}}
    assert os_.apply(cfg, "settings") is cfg                              # nothing chosen: unchanged
    os_.choose("local_pictures", "off")
    out = os_.apply(cfg, "settings")
    assert out["local_pictures"] == {"enabled": False, "max_day": 120} and cfg["local_pictures"]["enabled"] is True
    os_.choose("auto_approve", "off")
    assert os_.apply({}, "gates") == {"auto_approve": {"enabled": False}}
    assert os_.apply(cfg, "settings")["data_story"] == "on"              # untouched switch stays


def test_only_listed_switches_and_values(state):
    with pytest.raises(ValueError):
        os_.choose("min_quality", "50")
    with pytest.raises(ValueError):
        os_.choose("data_story", "maybe")
    state.write_text('{"min_quality": {"value": "50"}, "data_story": {"value": "sideways"}}', encoding="utf-8")
    assert os_.load() == {}                                               # a hand-edited bad file changes nothing


def test_current_reads_the_merged_value():
    assert os_.current("auto_approve", {"gates": {"auto_approve": {"enabled": False}}}) == "off"
    assert os_.current("data_story", {"settings": {"data_story": "on"}}) == "on"


def test_telegram_settings_menu_and_choice(state, monkeypatch):
    from engine import telegram_bot as tb
    monkeypatch.setattr(os_, "rows", lambda: [{"key": "data_story", "label": "Chart Shorts when pictures run out",
                                               "now": "on", "why": "x", "other": "off", "other_why": "y"}])
    text, kb = tb.settings_menu()
    assert "Chart Shorts" in text and kb["inline_keyboard"][0][0]["callback_data"] == "set:data_story=off"
    assert "✅ Chart Shorts when pictures run out: OFF" in tb.settings_choose("data_story", "off")
    assert os_.load()["data_story"]["value"] == "off"
    assert "not on the list" in tb.settings_choose("min_quality", "1")
