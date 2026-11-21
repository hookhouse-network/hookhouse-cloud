"""20 Nov (owner: "100/100 means the content must be perfect, with quality and full potential to go viral and it will
earn money"; "our system must not crash or fail by any means")."""
import json
import threading
import time

import pytest

from engine import potential_gate as pg, topic_proof as tp

CH = {"id": "unsolved_after_dark", "name": "Unsolved After Dark", "type": "story", "niche": "true crime mysteries",
      "market": "US", "language": "en"}


@pytest.fixture
def vid(tmp_path):
    out = tmp_path / "v"
    out.mkdir()
    (out / "captions.srt").write_text("1\n00:00:00,200 --> 00:00:02,000\nA whole town vanished overnight.\n\n"
                                      "2\n00:00:02,000 --> 00:00:04,000\nNobody ever came back.\n", encoding="utf-8")
    it = {"id": "p1", "channel": "unsolved_after_dark", "topic": "The town that vanished", "out_dir": str(out),
          "file": "video.mp4", "made_at": 10.0}
    return {"it": it, "out": out, "meta": {"title": "The Town That Vanished Overnight", "description": "True story."}}


class Brain:
    def __init__(self, scores=None, fail=False):
        self.calls, self.scores, self.fail = [], scores, fail

    def ask_json(self, task, prompt, temperature=0.4):
        self.calls.append((task, prompt, temperature))
        if self.fail:
            raise RuntimeError("All models failed")
        return {"scores": self.scores, "fixes": ["open on the empty streets"], "summary": "ok"}, None


ALL9 = {c: 9 for c in pg.DEFAULT_RUBRICS["story"] + [pg.HUMAN]}     # 21 Nov: + the S10 human_feel score


def test_deterministic_hook_originality_and_ad_safety(vid):
    assert pg.deterministic(vid["it"], CH, vid["meta"], past_titles=["A different story"]) == []
    (vid["out"] / "captions.srt").write_text("1\n00:00:01,500 --> 00:00:03,000\nSo, today...\n", encoding="utf-8")
    assert any("speech starts at 1.5s" in p for p in pg.deterministic(vid["it"], CH, vid["meta"], past_titles=[]))
    assert any("nearly repeats" in p for p in pg.deterministic(
        vid["it"], CH, vid["meta"], past_titles=["The Town That Vanished Over Night"]))
    bad = dict(vid["meta"], description="the gory details")
    assert any("advertiser-friendly" in p for p in pg.deterministic(vid["it"], CH, bad, past_titles=[]))


def test_every_criterion_must_reach_nine(vid, monkeypatch):
    monkeypatch.setattr("engine.content_gate.temporary_bar", lambda today=None: {})   # the strict rule itself
    monkeypatch.setattr(pg, "deterministic", lambda *a, **k: [])
    monkeypatch.setattr(tp, "proof", lambda topic, ch, **k: {"tier": "hot", "best_per_day": 90000, "top": []})
    b = Brain(dict(ALL9))
    assert pg.problems(vid["it"], CH, vid["meta"], brain_fn=lambda: b) == []
    task, prompt, temp = b.calls[0]
    assert task == "checker" and temp == 0.0 and "A whole town vanished" in prompt and "demand: hot" in prompt
    assert pg.problems(vid["it"], CH, vid["meta"], brain_fn=lambda: b) == [] and len(b.calls) == 1   # cached
    vid["it"]["made_at"] = 11.0                                      # a new version is judged again
    b2 = Brain(dict(ALL9, shareability=7, hook=8))
    probs = pg.problems(vid["it"], CH, vid["meta"], brain_fn=lambda: b2)
    assert probs and probs[0].startswith("potential: below 9/10 on shareability 7, hook 8") and "empty streets" in probs[0]


@pytest.mark.parametrize("brain, expect", [
    (lambda: None, "no AI judge"),
    (lambda: Brain(fail=True), "not judged yet"),
    (lambda: Brain({"hook": 10}), "skipped"),                         # partial answer = not judged
    (lambda: Brain(dict(ALL9, hook=42)), "invalid score"),
])
def test_not_judged_is_never_a_pass(vid, monkeypatch, brain, expect):
    monkeypatch.setattr(pg, "deterministic", lambda *a, **k: [])
    monkeypatch.setattr(tp, "proof", lambda topic, ch, **k: {"tier": "unknown"})
    probs = pg.problems(vid["it"], CH, vid["meta"], brain_fn=brain)
    assert probs and "not judged yet" in probs[0] and (expect in probs[0] or expect == "not judged yet")


def test_kids_and_clips_use_their_own_rubric(vid):
    b = Brain({c: 10 for c in pg.DEFAULT_RUBRICS["kids"] + [pg.HUMAN]})
    v = pg.judge(vid["it"], dict(CH, type="kids"), vid["meta"], b)
    assert set(v["scores"]) == set(pg.DEFAULT_RUBRICS["kids"] + [pg.HUMAN]) and "children aged 2-5" in b.calls[0][1]
    with pytest.raises(ValueError, match="skipped 'human_feel'"):     # S10 score missing = not judged
        pg.judge(vid["it"], dict(CH, type="kids"), vid["meta"], Brain({c: 10 for c in pg.DEFAULT_RUBRICS["kids"]}))
    b = Brain({c: 10 for c in pg.DEFAULT_RUBRICS["clips"]})
    assert set(pg.judge(dict(vid["it"], kind="clip"), CH, vid["meta"], b)["scores"]) == set(pg.DEFAULT_RUBRICS["clips"])


def test_remake_rules():
    from engine.content_gate import fixable_by_remake
    assert fixable_by_remake(["potential: below 9/10 on hook 7. Fix: x", "quality: score 93/100"])
    assert not fixable_by_remake(["potential: not judged yet (x); it tries again"])
    assert not fixable_by_remake(["potential: below 9/10 on hook 7", "fact-check missing"])


# ---------------------------------------------------------------- topic proof
class Resp:
    def __init__(self, data, ok=True):
        self._d, self.ok = data, ok

    def json(self):
        return self._d

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP 403")


class Session:
    def __init__(self, items, views):
        self.items, self.views, self.calls = items, views, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/search"):
            return Resp({"items": self.items})
        return Resp({"items": [{"id": k, "statistics": {"viewCount": v}} for k, v in self.views.items()]})


def _search_item(vid, days_ago, now):
    from datetime import datetime, timezone
    pub = datetime.fromtimestamp(now - days_ago * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": {"videoId": vid}, "snippet": {"title": f"Video {vid}", "publishedAt": pub}}


def test_topic_proof_tiers_cache_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "FILE", tmp_path / "proof.json")
    monkeypatch.setattr("engine.niche_winners._auth", lambda session=None: ({"key": "k"}, {}))
    monkeypatch.setattr("engine.publish.quota_ok", lambda units, bucket="general": True)
    monkeypatch.setattr("engine.publish.add_quota", lambda units, bucket="general": None)
    now = time.time()
    s = Session([_search_item("a", 2, now), _search_item("b", 10, now)], {"a": 400_000, "b": 30_000})
    p = tp.proof("The town that vanished", CH, session=s, now=now)
    assert p["tier"] == "hot" and 199_000 <= p["best_per_day"] <= 200_000 and p["top"][0]["title"] == "Video a"
    assert "views/day" in tp.evidence_text(p) and "Video a" in tp.evidence_text(p)
    n = len(s.calls)
    assert tp.proof("the town that VANISHED!", CH, session=s, now=now)["tier"] == "hot" and len(s.calls) == n
    empty = Session([], {})
    assert tp.proof("nobody makes this", CH, session=empty, now=now)["tier"] == "none"
    assert tp.proof("another topic", CH, session=empty, now=now, budget=2)["tier"] == "unknown"   # budget used


def test_topic_proof_without_access_is_unknown_not_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "FILE", tmp_path / "proof.json")
    monkeypatch.setattr("engine.niche_winners._auth", lambda session=None: None)
    assert tp.proof("x", CH)["tier"] == "unknown"


def test_cold_topics_are_replaced_once_with_the_evidence(monkeypatch):
    from engine import weekly
    tiers = {"Cold one": "cold", "Hot one": "hot", "New hot": "hot"}
    monkeypatch.setattr(tp, "proof", lambda topic, ch, **k: {"tier": tiers.get(topic, "warm"), "best_per_day": 1,
                                                              "top": []})
    monkeypatch.setattr("engine.topic_bank.hints", lambda cid, avoid: [])
    monkeypatch.setattr(weekly, "past_topics", lambda cid, limit=80: [])
    prompts = []

    class R:
        provider = "fake"

    class B:
        def ask_json(self, task, prompt, temperature=0.9):
            prompts.append(prompt)
            if len(prompts) == 1:
                return {"topics": [{"topic": "Cold one"}, {"topic": "Hot one"}]}, R()
            return {"topics": [{"topic": "New hot"}]}, R()
    ch = dict(CH, topic_hints=[])
    got = weekly.pick_topics(B(), ch, 2, log=lambda m: None)
    assert [t["topic"] for t in got] == ["Hot one", "New hot"]
    assert "Cold one (cold demand" in prompts[1] and got[0]["demand"].startswith("demand: hot")


# ---------------------------------------------------------------- the deadline saver
def test_deadline_guard_saves_then_ends_the_run():
    from engine.cloud import runner
    done, pushed = threading.Event(), []
    g = runner.deadline_guard(object(), log=lambda m: None, deadline_s=0.05,
                              exit_fn=lambda code: done.set(), push=lambda store: pushed.append(1) or 2048)
    assert done.wait(3) and pushed == [1]
    g.cancel()


def test_deadline_guard_cancelled_by_the_normal_save():
    from engine.cloud import runner
    fired = []
    g = runner.deadline_guard(object(), log=lambda m: None, deadline_s=0.2, exit_fn=lambda c: fired.append(c),
                              push=lambda s: 0)
    g.cancel()
    time.sleep(0.4)
    assert fired == []


def test_steps_are_isolated_and_timed(monkeypatch):
    from engine.cloud import runner
    monkeypatch.setattr(runner, "SLOW_STEP_S", -1.0)    # every step counts as slow (Windows' clock often measures 0 s)
    ran, logs, errors = [], [], {}
    runner._run_steps([("a", lambda: 1 / 0), ("b", lambda: ran.append("b"))], logs.append, errors)
    assert ran == ["b"] and "a" in errors and any("slow step" in m for m in logs)
