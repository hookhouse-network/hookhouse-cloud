"""Never-topics list + trend radar (offline: no network, fake AI)."""
from engine import policy, trends
from engine.campaign_safety import classify_banned

RSS = """<rss><channel>
<item><title>ipl 2026</title><ht:approx_traffic>2,000+</ht:approx_traffic>
<ht:news_item_title>IPL 2026 auction date announced</ht:news_item_title></item>
<item><title>xnxx</title><ht:approx_traffic>5000+</ht:approx_traffic></item>
<item><title><![CDATA[rajiv gandhi]]></title><ht:approx_traffic>200+</ht:approx_traffic>
<ht:news_item_title>Assassination anniversary</ht:news_item_title></item>
</channel></rss>"""


def test_modes_block_the_right_things():
    assert policy.topic_flags("XNXX", "trend") == ["adult"]
    assert "politics" in policy.topic_flags("Pete Hegseth, American politician", "trend")
    assert policy.topic_flags("the greatest shooting night in NBA history", "topic") == []     # sport, not a tragedy
    assert policy.topic_flags("one of the ship's pumps had been disassembled", "topic") == []
    assert policy.topic_flags("Jallianwala Bagh massacre 1919", "topic") == []                 # history, told with care
    assert policy.topic_flags("Jallianwala Bagh massacre 1919", "trend") == ["fresh_tragedy"]
    assert policy.topic_flags("intraday tips to double money", "topic") == ["financial_advice"]
    assert policy.topic_flags("सांप्रदायिक दंगा", "topic") == ["hate"]
    assert policy.topic_flags("सट्टा किंग", "topic") == ["gambling"]
    assert policy.topic_flags("Karna gives away his divine armour", "topic") == []
    assert "respectfully" in policy.never_rules_text()


def test_campaign_gate_uses_the_shared_list():
    assert any("never-topic" in h or "adult" in h for h in classify_banned("Promote our OnlyFans-style app"))
    assert classify_banned("Clip our cooking podcast") == []


def test_trend_feed_parsing_and_safety():
    items = trends.parse_trends_rss(RSS, "IN")
    assert [i["title"] for i in items] == ["ipl 2026", "xnxx", "rajiv gandhi"]
    assert items[0]["score"] == 2000 and "auction" in items[0]["extract"]
    safe = [i["title"] for i in items if trends.is_safe(i)[0]]
    assert safe == ["ipl 2026"]
    assert trends.SITE_PAGES.match(".xyz") and trends.SITE_PAGES.match("Main_Page")
    assert not trends.SITE_PAGES.match("Ramayana:_Part_1")


class FakeBrain:
    def ask_json(self, task, prompt, **kw):
        assert "Never make a video about" in prompt                 # the never-list travels with the request
        return ({"itihaas_ke_raaz": [{"i": 0, "angle": "What Valmiki wrote vs the film"}, {"i": 99}],
                 "money_cheat_codes": [{"i": 1, "angle": "How one chip firm hit $5T"}, {"i": 0}],
                 "not_a_channel": [{"i": 0}]}, None)


def test_ai_assignment_respects_markets_and_bad_answers():
    items = [{"source": "wikipedia:hi", "title": "रामायणम् (2026 फिल्म)", "key": "x", "score": 29710, "spike": 16.4,
              "lang": "hi", "desc": ""},
             {"source": "wikipedia:en", "title": "Nvidia", "key": "Nvidia", "score": 142333, "spike": 28.1, "lang": "en",
              "desc": "American multinational technology company"}]
    profiles = [{"id": "itihaas_ke_raaz", "market": "IN", "language": "hi", "profile": "mythology"},
                {"id": "money_cheat_codes", "market": "US", "language": "en", "profile": "money and tech"}]
    out = trends.assign_with_brain(FakeBrain(), items, profiles)
    assert [i["title"] for i in out["itihaas_ke_raaz"]] == ["रामायणम् (2026 फिल्म)"]     # bad index 99 ignored
    assert [i["title"] for i in out["money_cheat_codes"]] == ["Nvidia"]                    # Hindi item not for US
    assert "not_a_channel" not in out
    hint = trends.hint_text(out["money_cheat_codes"][0])
    assert "28.1x its usual" in hint and "Angle idea: How one chip firm" in hint


def test_affiliate_links_are_off_by_default_and_never_for_kids(monkeypatch):
    from engine import affiliate
    from engine.config import channel
    s = {"sources": ["Mary Celeste"], "title": "The Ship Found Sailing With Nobody Aboard"}
    monkeypatch.delenv("AMAZON_COM_TAG", raising=False)
    assert affiliate.links(channel("unsolved_after_dark"), s) == []
    monkeypatch.setenv("AMAZON_COM_TAG", "test-20")
    out = affiliate.links(channel("unsolved_after_dark"), s)
    assert "amazon.com/s?k=Mary+Celeste+book&tag=test-20" in out[0] and "Associate" in out[1]
    assert affiliate.links(channel("bloop_and_friends"), s) == []
    assert affiliate.links(channel("unsolved_after_dark"), {"sources": ["Online casino"], "title": "casino tricks"}) == []


def test_topic_bank_skips_covered_subjects(tmp_path, monkeypatch):
    import json
    from engine import topic_bank
    bank = tmp_path / "bank.json"
    bank.write_text(json.dumps({"space": [["Black hole", 2200000], ["Apollo 13", 1600000], ["Mars", 1300000]]}))
    monkeypatch.setattr(topic_bank, "BANK", bank)
    out = topic_bank.hints("cosmos_unboxed", avoid=["Apollo 13: the oxygen tank"], k=5, seed=1)
    assert len(out) == 2 and out[0].startswith("Black Hole") and not any("Apollo" in h for h in out)
