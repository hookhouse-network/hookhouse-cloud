"""Story text rules: Reel hook is a whole phrase, Instagram gets no YouTube-only tags, honest AI line."""
from engine import story


def test_reel_hook_is_a_complete_phrase():
    s = {"hook_text": "1¢ coin. 3.69¢ to make.", "title": "Why a Penny Costs Almost 4 Cents to Make",
         "title_options": ["Why a Penny Costs Almost 4 Cents to Make", "This 1-Cent Coin Cost 3.69 Cents"]}
    assert story._alt_hook(s) == "This 1-Cent Coin Cost 3.69 Cents"            # the whole title that fits
    long_only = {"hook_text": "x", "title_options": ["The Day a Whole Lake Vanished Into a Salt Mine Under Louisiana"]}
    hook = story._alt_hook(long_only)
    assert len(hook.split()) <= 8 and hook.split()[-1].lower() not in story.HANGING


def test_description_ai_line_and_single_disclaimer():
    ch = {"name": "Money Cheat Codes", "hashtags": ["#money"],
          "content_rules": {"disclaimer": "Education only, not financial advice."}}
    photos_only = story.build_description(ch, {"hook_text": "h", "summary": "S. Education only, not financial advice."},
                                          ["Pile of pennies (CC0), Wikimedia Commons"])
    assert photos_only.count("not financial advice") == 1
    assert "AI-generated" not in photos_only and "AI voice" in photos_only
    with_ai = story.build_description(ch, {"hook_text": "h", "summary": "S."}, ["AI-generated image"])
    assert "some visuals are AI-generated" in with_ai and with_ai.count("not financial advice") == 1


def test_instagram_tags_drop_youtube_only_ones():
    assert "#shorts" in story.YT_ONLY_TAGS
    tags = [t for t in dict.fromkeys(["#penny", "#shorts", "#money", "#YouTubeShorts"]) if t.lower() not in story.YT_ONLY_TAGS]
    assert tags == ["#penny", "#money"]


def test_officials_photos_need_the_person_in_the_scene():
    meta = "Secretary of Labor Elaine L. Chao speaks at a Mine Safety and Health Administration event, Washington"
    assert story.OFFICIAL.search(meta)
    assert not story._shares_name(meta, "The drill hit the wrong mine and the lake drained")   # generic words only
    assert story._shares_name(meta, "Elaine Chao announced new mine safety rules")
    assert not story.OFFICIAL.search("Salt mine tunnel, Avery Island, Louisiana")


def test_stock_pictures_need_a_real_keyword_match():
    assert not story._lexical_ok("memory", "Old woman portrait wrinkles close up")
    assert not story._lexical_ok("idea TV show", "chalkboard with handwriting")
    assert story._lexical_ok("Genoa harbor 1872", "Aerial view of Genoa city and port")
    assert story._lexical_ok("salt mine Louisiana", "Salt mine tunnel, Avery Island, Louisiana")
    assert story._lexical_ok("", "anything")                      # no query words: nothing to check


def test_ancient_channels_never_get_modern_people_or_scenes():
    assert story.MODERN.search("Karna Kumar, Indian entrepreneur, at a startup event in 2016")
    assert story.MODERN.search("Destroyed house after shelling, soldiers inspect the ruins")
    assert not story.MODERN.search("Konark Sun Temple chariot wheel, 13th century, Odisha")
    assert not story.MODERN.search("Bronze sculpture of Surya, Chola period")


def test_fact_fix_never_makes_a_script_worse(monkeypatch):
    verdicts = iter([{"checked": True, "ok": False, "problems": ["wrong year"], "warnings": []},
                     {"checked": True, "ok": False, "problems": ["new mistake 1", "new mistake 2"], "warnings": []},
                     {"checked": True, "ok": False, "problems": ["new mistake 3", "new mistake 4"], "warnings": []}])
    monkeypatch.setattr(story, "fact_check", lambda brain, script, deep=False: next(verdicts))

    def fake_fix(brain, script, wrong):
        script["beats"][0]["narration"] = "edited"
        return script, 1
    monkeypatch.setattr(story, "fix_script", fake_fix)
    script = {"beats": [{"narration": "original"}], "claims": []}
    out = story.check_and_fix(None, {"content_rules": {}}, script, "topic", "short", log=lambda m: None)
    assert out["beats"][0]["narration"] == "original"            # the first (best) version was kept
    assert out["_fact_check"]["problems"] == ["wrong year"]


def test_unsupported_details_alone_do_not_trigger_a_rewrite(monkeypatch):
    monkeypatch.setattr(story, "fact_check",
                        lambda brain, script, deep=False: {"checked": True, "ok": True, "problems": [], "warnings": ["x"]})
    monkeypatch.setattr(story, "fix_script", lambda *a: (_ for _ in ()).throw(AssertionError("must not fix")))
    out = story.check_and_fix(None, {}, {"beats": [{"narration": "a"}]}, "t", "short", log=lambda m: None)
    assert out["_fact_check"]["warnings"] == ["x"]


def test_heads_of_state_photos_need_their_own_scene():
    meta = "Vladimir Putin and Vladislav Tretiak, President of Russia meeting, Kremlin 2016"
    scene = "Vladislav Tretiak was pulled after the first period"
    assert any(w in meta.lower() and w not in scene.lower() for w in story.SENSITIVE)


def test_without_ai_images_scenes_get_concrete_searches(monkeypatch):
    monkeypatch.setattr(story.visuals, "ai_image_available", lambda: False)
    s = story.normalize_script({"beats": [{"visual": "ai", "narration": "One theory:",
                                           "ai_prompt": "Cinematic wide shot of a 1980 Texaco oil drilling rig, dramatic"}]})
    assert s["beats"][0]["visual"] == "photo" and s["beats"][0]["query"] == "Texaco oil drilling rig"
    assert story.SPACE.search("Whirlpool Galaxy M51, Hubble") and not story.SPACE.search("the lake became a whirlpool")


def test_heroes_never_charts_or_nudity():
    assert story.NUDITY.search("A nude sea nymph painting") and story.NUDITY.search("The Bathers by Cezanne")
    assert not story.NUDITY.search("Venus planet radar image") and not story.NUDITY.search("Elephants bathing in a river")
    assert story.CHART_WORDS.search("Pressure-density curve of seawater, figure 3")


def test_srt_captions_and_seo_tags(tmp_path):
    from engine.clips import Word
    ws = [Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate("the miracle on ice happened in nineteen eighty at lake placid".split())]
    srt = story.write_srt(ws, tmp_path / "c.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> ") and "\n2\n" in srt          # 11 words -> 2 cues of <= 7
    tags = story.seo_tags({"name": "Clutch Tales"}, {"search_phrase": "Miracle on Ice 1980", "hashtags": ["#hockey", "#Olympics"]})
    assert tags[0] == "Miracle on Ice 1980" and "hockey" in tags and tags[-1] == "Clutch Tales"


def test_fit_length_only_removes_and_keeps_the_hook():
    beats = [{"narration": " ".join(["word"] * 12), "visual": "photo", "query": f"q{i}"} for i in range(16)]   # 192 words
    ch = {"spec": {"short_words": "110-135 words"}}

    class B:
        def ask_json(self, role, prompt, temperature=0.3):
            return {"keep": [{"i": i, "narration": " ".join(["word"] * 10)} for i in range(0, 16) if i % 4 != 2]}, None

    out = story.fit_length(B(), ch, {"beats": beats, "_fact_check": {"ok": True}}, log=lambda *a: None)
    n = sum(len(b["narration"].split()) for b in out["beats"])
    assert n == 120 and out["beats"][0]["query"] == "q0" and out["_fact_check"] == {}
    same = story.fit_length(B(), ch, {"beats": beats[:10]}, log=lambda *a: None)     # 120 words: already in range
    assert len(same["beats"]) == 10


def test_on_screen_numbers_follow_the_narration():
    b = {"narration": "Salt water roars in as a 164-foot waterfall.", "big_text": "150-FOOT WATERFALL", "label": "REAL PHOTO · 1980"}
    story._sync_numbers(b)
    assert b["big_text"] == "164-FOOT WATERFALL" and b["label"] == "REAL PHOTO · 1980"
    b2 = {"narration": "They lost 10 to 3, then won 4 to 3.", "big_text": "11-3", "label": ""}
    story._sync_numbers(b2)
    assert b2["big_text"] == ""
    b3 = {"narration": "Ten seconds left.", "big_text": "10 SECONDS", "label": ""}
    story._sync_numbers(b3)
    assert b3["big_text"] == "10 SECONDS"
