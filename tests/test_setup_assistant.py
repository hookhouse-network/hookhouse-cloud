"""Setup assistant (owner, 12 Nov 2026: "a playwright script for all the account setups and required key setups").
Everything except the real browser is tested here: steps, key capture, checks, savers, matching and the local server."""
import json
import time
import urllib.request

import pytest

from engine import setup_assistant as sa
from engine import setup_steps as ss


class R:
    def __init__(self, data=None, code=200):
        self.data, self.status_code, self.ok = data or {}, code, code == 200

    def json(self):
        return self.data

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "ENV", tmp_path / ".env")
    monkeypatch.setattr(ss, "PROGRESS", tmp_path / "progress.json")
    monkeypatch.setattr(ss, "SECRETS", tmp_path / "secrets")
    return tmp_path


def test_steps_cover_every_channel_key_and_todo():
    from engine import todo
    from engine.config import channels
    st = ss.steps()
    ids = {s["id"] for s in st}
    for ch in channels():
        assert f"yt_{ch['id']}" in ids
        assert (f"meta_{ch['id']}" in ids) == (ch.get("type") != "kids")      # no Instagram/Facebook for kids
    todo_ids = {t["id"] for t in todo.load()}
    for s in st:
        # the owner's to-do list is private (not in the public code repo; the cloud gets it from its memory)
        assert not s["todo"] or not todo_ids or s["todo"] in todo_ids, s["id"]
        for f in s["fields"]:
            assert f["kind"] != "env" or f["id"] in ss.KEYS
        for k in s["scan"]:
            assert k in ss.KEYS or k in sa.SPECIAL
    assert st[-1]["id"] == "doctor" and len(ids) == len(st)


def test_save_env_replaces_and_appends(tmp_state, monkeypatch):
    (tmp_state / ".env").write_text("# keep me\nGROQ_API_KEY=# placeholder\nOTHER=1\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ss.save_env("GROQ_API_KEY", "gsk_x")
    ss.save_env("NEW_KEY", "v")
    text = (tmp_state / ".env").read_text(encoding="utf-8")
    assert "# keep me" in text and "GROQ_API_KEY=gsk_x" in text and "OTHER=1" in text and text.endswith("NEW_KEY=v\n")
    assert ss.env_file_value("GROQ_API_KEY") == "gsk_x"


def test_candidates_find_keys_and_skip_ones_in_use(monkeypatch):
    tok = "123456789:" + "A" * 35
    assert ss.candidates("TELEGRAM_BOT_TOKEN", f"Use this token to access the HTTP API:\n{tok}\nKeep it secure") == [tok]
    g = "AIza" + "b" * 35
    monkeypatch.setenv("GEMINI_API_KEY", g)
    assert ss.candidates("YOUTUBE_API_KEY", f"keys: {g} AIza{'c' * 35}") == ["AIza" + "c" * 35]   # Gemini's key skipped
    assert ss.candidates("CLOUDFLARE_ACCOUNT_ID", "", "https://dash.cloudflare.com/" + "a1" * 16 + "/ai") == ["a1" * 16]
    assert ss.candidates("META_APP_ID", "", "https://developers.facebook.com/apps/123456789012345/settings/basic/") == ["123456789012345"]
    assert ss.candidates("CONTACT_URL", "https://x") == []                     # typed, never scraped


def test_key_checks_use_the_services(monkeypatch):
    class S:
        def get(self, url, **k):
            if "telegram" in url:
                return R({"ok": True, "result": {"username": "hookhouse_control_bot"}})
            if "groq" in url:
                return R(code=401)
            return R({})
    assert ss.check_key("TELEGRAM_BOT_TOKEN", "1:x", S()) == (True, "bot @hookhouse_control_bot found")
    assert ss.check_key("GROQ_API_KEY", "gsk_bad", S())[0] is False
    assert ss.check_key("CONTACT_URL", "mailto:me@x.com")[0] is False
    assert ss.check_key("CONTACT_URL", "https://sites.google.com/view/hookhouse")[0] is True
    assert ss.check_key("AMAZON_IN_TAG", "hookhouse-21")[0] and not ss.check_key("AMAZON_IN_TAG", "hookhouse-20")[0]
    assert ss.check_key("POSTAL_ADDRESS", "PO Box 12, Andheri, Mumbai 400053")[0]


def test_google_client_file():
    raw = json.dumps({"installed": {"client_id": "1-a.apps.googleusercontent.com", "client_secret": "GOCSPX-x"}})
    assert ss.google_client_from_json(raw) == ("1-a.apps.googleusercontent.com", "GOCSPX-x")
    assert ss.google_client_from_json("{}") is None and ss.google_client_from_json("not json") is None


def test_meta_connect_matches_pages_to_channels(monkeypatch):
    import engine.connect as connect
    import engine.links as links
    saved, linked = [], []
    monkeypatch.setattr(connect, "meta_long_lived", lambda t, s=None: ("LONG", 123.0))
    monkeypatch.setattr(connect, "save_meta", lambda *a, **k: saved.append((a, k)))
    monkeypatch.setattr(links, "set_link", lambda cid, **f: linked.append((cid, f)))

    class S:
        def get(self, url, **k):
            assert k["params"]["access_token"] == "LONG"
            return R({"data": [
                {"id": "P1", "name": "Deep Blue Files", "access_token": "PT1",
                 "instagram_business_account": {"id": "IG1", "username": "deepbluefiles"}},
                {"id": "P2", "name": "Some Other Page", "access_token": "PT2",
                 "instagram_business_account": {"id": "IG2", "username": "clutchtales"}},     # matched by username
                {"id": "P3", "name": "Unrelated", "access_token": "PT3"}]})
    out = ss.meta_connect("EAAshort", S())
    chans = {a[0] for a, k in saved}
    assert chans == {"deep_blue_files", "clutch_tales"}
    rec = next((a, k) for a, k in saved if a[0] == "deep_blue_files")
    assert rec[0][1:5] == ("IG1", "P1", "LONG", "PT1") and rec[1]["expires_at"] == 123.0
    assert ("deep_blue_files", {"instagram": "deepbluefiles"}) in linked and len(out) == 2


def test_telegram_channel_needs_admin_rights(monkeypatch):
    import engine.links as links
    linked = []
    monkeypatch.setattr(links, "set_link", lambda cid, **f: linked.append((cid, f)))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:x")
    status = {"v": "member"}

    class S:
        def get(self, url, **k):
            if url.endswith("getMe"):
                return R({"ok": True, "result": {"id": 42}})
            if url.endswith("getChat"):
                return R({"ok": True, "result": {"id": -100}})
            return R({"ok": True, "result": {"status": status["v"], "can_post_messages": True}})
    assert "as an admin" in ss.telegram_channel("deep_blue_files", "deepbluefiles", S()) and not linked
    status["v"] = "administrator"
    assert "✅ @deepbluefiles saved" in ss.telegram_channel("deep_blue_files", "https://t.me/deepbluefiles", S())
    assert linked == [("deep_blue_files", {"telegram": "@deepbluefiles"})]


def test_dailymotion_checks_then_saves(tmp_state):
    class S:
        def __init__(self, code):
            self.code = code

        def post(self, url, **k):
            return R({"access_token": "t"}, self.code)
    assert "refused" in ss.dailymotion("k", "s", "p", S(401))
    assert "profile id" in ss.dailymotion("k", "s", "", S(200))
    assert "✅" in ss.dailymotion("k", "s", "x1abc", S(200))
    rec = json.loads((tmp_state / "secrets" / "dailymotion.json").read_text())
    assert rec["client_id"] == "k" and rec["profiles"]["deep_blue_files"] == "x1abc" and "hot_take_hq" not in rec["profiles"]


def test_pacing_counts_new_accounts_per_platform_per_day(tmp_state):
    ss.mark("yt_deep_blue_files", "created")
    ss.mark("yt_clutch_tales", "created")
    ss.mark("meta_clutch_tales", "created")
    p = ss.progress()
    p["created"]["yt_old"] = time.time() - 3 * 86400
    ss._save_progress(p)
    first = ss.progress()["created"]["yt_deep_blue_files"]
    ss.mark("yt_deep_blue_files", "created")                                   # connecting later keeps the first date
    assert ss.progress()["created"]["yt_deep_blue_files"] == first
    assert ss.created_today("youtube") == 2 and ss.created_today("meta") == 1


def test_pair_poll_saves_the_chat(monkeypatch, tmp_state):
    import engine.telegram_bot as tb
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:x")
    got = []
    monkeypatch.setattr(tb, "_try_pair", lambda chat, text: got.append((chat, text)) or text == "123456")

    class S:
        def get(self, url, **k):
            return R({"ok": True, "result": [{"update_id": 5, "message": {"chat": {"id": 77}, "text": "hi"}},
                                             {"update_id": 6, "message": {"chat": {"id": 77}, "text": "123456"}}]})
    assert "Paired" in ss.pair_poll(None, deadline_s=5, s=S(), sleep=lambda x: None)
    assert got[-1] == ("77", "123456")


def test_scan_saves_only_expected_keys_from_allowed_pages(monkeypatch):
    saved = []
    monkeypatch.setattr(ss, "submit_key", lambda n, v, s=None: saved.append((n, v)) or (True, "ok"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    sa.STATE["tried"] = set()
    groq = "gsk_" + "Z" * 52
    step = {"scan": ["GROQ_API_KEY"]}
    sa.scan_text(step, "https://www.instagram.com/", groq)                    # a social app: never read
    sa.scan_text({"scan": []}, "https://console.groq.com/keys", groq)         # not this step's key
    sa.scan_text(step, "https://console.groq.com/keys", f"Your new key {groq}")
    sa.scan_text(step, "https://console.groq.com/keys", f"Your new key {groq}")   # tried once only
    two = "1234567-abcdefghijkl.apps.googleusercontent.com 7654321-zyxwvutsrqpo.apps.googleusercontent.com"
    sa.scan_text({"scan": ["YOUTUBE_CLIENT_ID"]}, "https://console.cloud.google.com/auth/clients", two)  # ambiguous
    time.sleep(0.3)
    assert saved == [("GROQ_API_KEY", groq)]


def test_local_server_needs_the_session_token():
    srv, url = sa.start_server()
    try:
        base = url.split("/?")[0]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/steps", timeout=10)
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/steps", headers={"X-Token": sa.STATE["token"]})
        steps = json.loads(urllib.request.urlopen(req, timeout=10).read())["steps"]
        assert steps[0]["id"] == "welcome"
        post = urllib.request.Request(base + "/api/key", data=b'{"name":"GROQ_API_KEY","value":"x"}',
                                      headers={"X-Token": sa.STATE["token"], "Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError) as e2:                       # form posts from other sites: refused
            urllib.request.urlopen(post, timeout=10)
        assert e2.value.code == 403
        img = urllib.request.Request(base + "/file?p=.env&t=" + sa.STATE["token"])
        with pytest.raises(urllib.error.HTTPError):                              # only brand images / products
            urllib.request.urlopen(img, timeout=10)
    finally:
        srv.shutdown()
