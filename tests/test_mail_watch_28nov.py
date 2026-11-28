"""28 Nov (owner: warning mails sat unread): the daily mail watch reports new restriction / failure mails once,
skips promotions and resolved notices, and flags unknown senders as possible phishing."""
from engine import mail_watch as mw

ROWS = [
    {"from": "noreply@business.facebook.com", "name": "Meta for Business",
     "subject": "[Action required] We've restricted your business account", "snippet": "", "date": "28 Nov 02:53"},
    {"from": "pinbot@legal.pinterest.com", "name": "Pinterest", "subject": "Your account status has changed",
     "snippet": "Your account was deactivated for spam", "date": "26 Nov"},
    {"from": "notifications@github.com", "name": "hookhouse-network",
     "subject": "[hookhouse-network/hookhouse-cloud] Run failed: tick - main (86afa8a)", "snippet": "", "date": "27 Nov"},
    {"from": "pinbot@pinterest.com", "name": "Pinterest", "subject": "3 tips for creating great Pins", "snippet": "",
     "date": "24 Nov"},
    {"from": "noreply@mail.instagram.com", "name": "Instagram", "subject": "You're back on Instagram, brainsnackdose",
     "snippet": "does follow our Community Standards", "date": "25 Nov"},
    {"from": "security@meta-support-check.xyz", "name": "Meta Support", "subject": "URGENT: verify your page now",
     "snippet": "", "date": "28 Nov"},
]


def test_warnings_are_found_and_noise_skipped():
    subjects = [r["subject"] for r in mw.classify(ROWS)]
    assert any("restricted" in s for s in subjects) and any("status has changed" in s for s in subjects)
    assert any("Run failed" in s for s in subjects)
    assert not any("tips" in s or "back on Instagram" in s for s in subjects)


def test_unknown_senders_are_flagged_as_possible_phishing():
    warns = {r["name"]: r for r in mw.classify(ROWS)}
    assert warns["Meta for Business"]["trusted"] and not warns["Meta Support"]["trusted"]
    assert "could be phishing" in mw.message([warns["Meta Support"]])


def test_each_mail_is_reported_once(monkeypatch, tmp_path):
    monkeypatch.setattr(mw, "SEEN", tmp_path / "seen.json")
    monkeypatch.setattr(mw, "STATE", tmp_path / "state.txt")
    sent = []
    assert mw.run(log=lambda *a: None, send=sent.append, rows=ROWS) == 4
    assert "4 new warning email(s)" in sent[0]
    assert mw.run(log=lambda *a: None, send=sent.append, rows=ROWS) == 0 and len(sent) == 1
