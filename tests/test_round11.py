"""Round 11 (12-13 Nov): catchphrases and SEO inside every video, Hindi-aware phrase checks, YouTube branding by API."""
import json

from engine import branding, quality


def test_hindi_narration_counts_as_saying_the_search_phrase():
    assert quality.said(["karna", "kavach", "kundal"], "कर्ण ने खुद कवच कुंडल काटकर इंद्र को दे दिए!")
    assert quality.said(["dadasaheb", "phalke"], "ये दादासाहेब फाल्के की कहानी है.")
    assert quality.said(["mariana", "trench"], "The Mariana Trench is 11 km deep.")
    assert not quality.said(["mariana", "trench"], "Nobody had ever been this deep.")


def test_seo_issues_flag_missing_phrase_and_catchphrase():
    ch = {"type": "story", "catchphrase": "The deep is still keeping secrets."}
    good = {"search_phrase": "Mariana Trench", "beats": [{"narration": "The Mariana Trench swallowed a sub."},
                                                          {"narration": "x"},
                                                          {"narration": "The deep is still keeping secrets."}]}
    assert quality.seo_issues(ch, good, {"description": "The Mariana Trench is the deepest place."}, "long") == []
    bad = {"search_phrase": "Mariana Trench", "beats": [{"narration": "Nobody came back."}, {"narration": "x"},
                                                         {"narration": "Goodbye."}]}
    msgs = [m for _, m in quality.seo_issues(ch, bad, {"description": "A strange story."}, "long")]
    assert len(msgs) == 3 and "catchphrase" in msgs[2]
    assert len(quality.seo_issues(ch, bad, {}, "short")) == 1                 # Shorts loop: no sign-off needed


def test_descriptions_carry_the_catchphrase():
    from engine import story
    from engine.config import channel
    d = story.build_description({"id": "x", "name": "Deep Blue Files", "language": "en",
                                 "catchphrase": "The deep is still keeping secrets."},
                                {"summary": "The Trieste reached the bottom in 1960."}, [])
    assert "The deep is still keeping secrets." in d
    for cid in ("brain_snack", "bloop_and_friends"):
        assert channel(cid).get("catchphrase")
    for ch_id in ("deep_blue_files", "itihaas_ke_raaz", "hot_take_hq"):
        ch = channel(ch_id)
        assert ch.get("about") and len(ch.get("keywords") or []) >= 3 and ch["handles"]["youtube"].startswith("@")


def test_branding_texts():
    ch = {"id": "x", "about": "Real stories.", "keywords": ["true crime", "mystery", 'bad"quote'], "language": "hi"}
    assert branding.keywords_text(ch) == '"true crime" mystery badquote'
    long = {"keywords": [f"keyword number {i}" for i in range(60)]}
    assert len(branding.keywords_text(long)) <= 500


def test_about_never_shows_an_email(monkeypatch):
    ch = {"about": "Real stories."}
    monkeypatch.setenv("CONTACT_URL", "mailto:someone@example.com")
    assert "@" not in branding.about_text(ch)
    monkeypatch.setenv("CONTACT_URL", "https://sites.google.com/view/hookhouse")
    assert branding.about_text(ch).endswith("https://sites.google.com/view/hookhouse")


def test_merged_settings_keep_existing_values():
    cur = {"channel": {"title": "Old", "unsubscribedTrailer": "abc", "keywords": "old"},
           "image": {"bannerExternalUrl": "https://old"}}
    out = branding.merged_settings(cur, {"about": "New about", "keywords": ["a b"], "language": "hi"}, "https://new")
    assert out["channel"]["unsubscribedTrailer"] == "abc" and out["channel"]["description"].startswith("New about")
    assert out["channel"]["keywords"] == '"a b"' and out["channel"]["country"] == "IN"
    assert out["channel"]["defaultLanguage"] == "hi" and out["image"]["bannerExternalUrl"] == "https://new"
    assert cur["channel"]["keywords"] == "old"                                 # input not changed


def test_branding_apply_writes_once(tmp_path, monkeypatch):
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "youtube_x.json").write_text("{}")
    brand = tmp_path / "brand" / "x"
    brand.mkdir(parents=True)
    (brand / "youtube_banner.jpg").write_bytes(b"\xff\xd8fakejpeg")
    monkeypatch.setattr(branding, "STATE", tmp_path / "branding.json")
    monkeypatch.setattr(branding, "BRAND", tmp_path / "brand")
    monkeypatch.setattr(branding, "yt_token_path", lambda c: sec / f"youtube_{c}.json")
    monkeypatch.setattr(branding, "yt_access_token", lambda c, s=None: "tok")
    monkeypatch.setattr(branding, "quota_ok", lambda u, b="general": True)
    monkeypatch.setattr(branding, "add_quota", lambda u, b="general": None)
    calls = []

    class R:
        def __init__(self, data):
            self.data, self.ok, self.status_code, self.text = data, True, 200, ""

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class S:
        def get(self, url, **k):
            calls.append("list")
            return R({"items": [{"id": "UC1", "brandingSettings": {"channel": {"title": "X"}}}]})

        def post(self, url, **k):
            calls.append("banner")
            return R({"url": "https://banner"})

        def put(self, url, **k):
            calls.append(json.loads(k["data"]))
            return R({})
    ch = {"id": "x", "name": "X", "about": "About X", "keywords": ["x y"], "language": "en"}
    assert "banner" in branding.apply(ch, S())
    body = calls[-1]
    assert body["id"] == "UC1" and body["brandingSettings"]["image"]["bannerExternalUrl"] == "https://banner"
    assert body["brandingSettings"]["channel"]["description"].startswith("About X")
    assert "up to date" in branding.apply(ch, S())                             # nothing changed: no API calls
    assert len(calls) == 3


# --- creator outreach: the system sends after the owner's tap (HookHouse Gmail, send-only) ---------------------
def _gmail_env(tmp_path, monkeypatch, address="PO Box 12, Mumbai 400001, India"):
    from engine import gmail
    tok = tmp_path / "gmail_outreach.json"
    tok.write_text("{}")
    monkeypatch.setattr(gmail, "GMAIL_TOKEN", tok)
    monkeypatch.setattr(gmail, "SENT", tmp_path / "sent.json")
    monkeypatch.setattr(gmail, "OPTOUT", tmp_path / "optout.json")
    monkeypatch.setattr(gmail, "google_access_token", lambda p, s=None: "tok")
    if address:
        monkeypatch.setenv("POSTAL_ADDRESS", address)
    else:
        monkeypatch.delenv("POSTAL_ADDRESS", raising=False)
    return gmail


class _Post:
    def __init__(self):
        self.sent = []

    def post(self, url, **k):
        self.sent.append(k["json"])

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"id": "m1", "threadId": "t1"}
        return R()


def test_gmail_needs_postal_address_and_adds_opt_out(tmp_path, monkeypatch):
    gmail = _gmail_env(tmp_path, monkeypatch, address="")
    ok, why = gmail.ready()
    assert not ok and "POSTAL_ADDRESS" in why
    gmail = _gmail_env(tmp_path, monkeypatch)
    msg, mid = gmail.build("hello@show.com", "Clips for your show", "Hi there", None)
    body = msg.get_content()
    assert "PO Box 12, Mumbai" in body and "no thanks" in body and msg["Subject"] == "Clips for your show"
    re_msg, _ = gmail.build("hello@show.com", "Clips for your show", "Following up", {"message_id": mid,
                                                                                  "thread_id": "t1"})
    assert re_msg["Subject"].startswith("Re: ") and re_msg["In-Reply-To"] == mid


def test_gmail_daily_cap_and_never_after_no(tmp_path, monkeypatch):
    gmail = _gmail_env(tmp_path, monkeypatch)
    s = _Post()
    assert gmail.send("hello@show.com", "Hi", "Body", session=s)["thread_id"] == "t1"
    gmail.opt_out("Hello@Show.com")
    import pytest
    with pytest.raises(RuntimeError, match="asked not to be emailed"):
        gmail.send("hello@show.com", "Hi", "Body", session=s)
    monkeypatch.setattr(gmail, "DAILY_MAX", 1)
    with pytest.raises(RuntimeError, match="limit"):
        gmail.send("other@show.com", "Hi", "Body", session=s)
    assert len(s.sent) == 1


def test_send_for_me_pitch_then_follow_up(tmp_path, monkeypatch):
    from engine import outreach, pitch
    import engine.telegram_bot as tb
    gmail = _gmail_env(tmp_path, monkeypatch)
    monkeypatch.setattr(pitch, "DB", tmp_path / "system.db")
    monkeypatch.setattr(pitch, "PITCHES", tmp_path)
    store = {}
    monkeypatch.setattr(tb, "_load", lambda: store)
    monkeypatch.setattr(tb, "_save", lambda s: None)
    conn = pitch.connect()
    pid = pitch.add(conn, "Big Pod")
    (tmp_path / f"{pid}.md").write_text("## Email\n**Subject:** Free clips for Big Pod\n\nHi Big Pod team...\n\n"
                                        "## Follow-up (day 3)\nJust checking in.\n\n## Follow-up (day 7)\nLast note.\n",
                                        encoding="utf-8")
    sent = []
    monkeypatch.setattr(gmail, "send", lambda to, subj, body, thread=None, session=None:
                        sent.append((to, subj, body, thread)) or {"id": "m", "thread_id": "t9", "message_id": "<x>",
                                                                  "subject": subj})
    assert "address first" in outreach.send_for_me(pid)                       # no address yet: nothing sent
    assert "Saved" in outreach.set_email(pid, "hello@bigpod.com")
    assert "Sent from the HookHouse Gmail" in outreach.decide("m", pid)
    assert sent[0][:2] == ("hello@bigpod.com", "Free clips for Big Pod") and sent[0][3] is None
    assert "Follow-up sent" in outreach.decide("fm", pid)
    assert sent[1][2] == "Just checking in." and sent[1][3] == {"thread_id": "t9", "message_id": "<x>"}
    assert "never emailed again" in outreach.decide("x", pid) and gmail.opted_out("hello@bigpod.com")
