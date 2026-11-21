"""P3r creativity (S8 A1): every fresh story video uses one proven structure, in rotation, saved on the script."""
import yaml

from engine import humanize, patterns


def test_library_is_complete_and_sounds_human():
    d = yaml.safe_load(patterns.FILE.read_text(encoding="utf-8"))
    assert len(d["patterns"]) >= 6 and {"bloop_and_friends", "brain_snack"} <= set(d["skip"])
    for p in d["patterns"]:
        assert p["name"] and len(p["shape"]) > 40
        assert not humanize.tells(p["shape"]), p["name"]


def test_rotation_rule_and_apply():
    names = [patterns.pick("cosmos_unboxed")["name"] for _ in range(8)]
    n = len(yaml.safe_load(patterns.FILE.read_text(encoding="utf-8"))["patterns"])
    assert len(set(names[:n])) == n and names[n] == names[0]                  # every pattern once, then again
    assert patterns.pick("bloop_and_friends") is None and patterns.rule(None) == ""
    p = patterns.pick("deep_blue_files")
    assert p["name"] in patterns.rule(p) and "hook in the first second comes first" in patterns.rule(p)
    assert patterns.apply({"title": "T"}, p) == {"title": "T", "pattern": p["name"]}
    assert patterns.apply({"title": "T"}, None) == {"title": "T"}
