"""Owner 17 Nov 2026: two different Brain Snack videos had the same title and looked like a double post."""
from engine import uniq


def test_unused_option_comes_first_and_a_detail_is_added_when_all_are_used():
    opts = ["Which try reaches the center? 😭", "It starts faster every try… 🧠"]
    used = {uniq._norm(opts[0])}
    assert uniq.pick("brain_snack", opts, used=used)[0] == opts[1]
    used.add(uniq._norm(opts[1]))
    first = uniq.pick("brain_snack", opts, used=used)[0]
    assert first == "Which try reaches the center? (Round 2) 😭"
    used.add(uniq._norm(first))
    assert uniq.pick("brain_snack", opts, used=used)[0] == "Which try reaches the center? (Round 3) 😭"


def test_used_titles_reads_the_publish_log(tmp_path, monkeypatch):
    import json
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"channel": "brain_snack", "done": True, "details": {"title": "Wait for the last try 😳"}}) + "\n")
    monkeypatch.setattr(uniq, "LOG", log)
    monkeypatch.setattr(uniq, "ROOT", tmp_path)
    assert uniq._norm("Wait for the last try 😳") in uniq.used_titles("brain_snack")
