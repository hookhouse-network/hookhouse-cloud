"""Storyboard (owner 15 Nov 2026: shots must SHOW what is said; light, fast, accurate). All network calls are fakes."""
import json
import time

import pytest
from PIL import Image

from engine import storyboard as sb


class FakeBrain:
    def __init__(self, data):
        self.data, self.prompts = data, []

    def ask_json(self, task, prompt, **k):
        self.prompts.append(prompt)
        return self.data, None


CH = {"id": "unsolved_after_dark", "name": "Creepy Case Club", "language": "en",
      "style": {"ai_style": "moody cinematic film still"}}


def _script(n=3):
    return {"title": "Lake", "beats": [{"narration": f"line {k}", "visual": "photo"} for k in range(n)]}


def test_plan_fills_every_beat_and_builds_prompts():
    data = {"bible": {"era": "Louisiana 1980", "cast": {"RIG": "tall steel derrick"}},
            "shots": [{"i": 1, "type": "scene", "see": "aerial lake with rig", "cast": ["RIG"], "action": "push_in"},
                      {"i": 2, "type": "number", "see": "close drill bit", "action": "spin"},
                      {"i": 3, "type": "real", "see": "the real island", "cast": []}]}
    s = _script()
    s["beats"][1]["big_text"] = "14 INCHES"
    assert sb.plan(FakeBrain(data), s, CH, log=lambda *a: None)
    b0, b1, b2 = s["beats"]
    assert b0["visual"] == "scene" and b0["action"] == "push_in"
    assert "tall steel derrick" in b0["_prompt"] and "Louisiana 1980" in b0["_prompt"] and "no text" in b0["_prompt"]
    assert b1["visual"] == "text" and b1["action"] == ""          # unknown action dropped
    assert b2["visual"] == "photo" and b2["_era"] == "Louisiana 1980"


def test_plan_failure_keeps_old_behaviour():
    s = _script()
    assert not sb.plan(FakeBrain(None), s, CH, log=lambda *a: None)
    assert all("see" not in b for b in s["beats"])


def test_sports_and_myth_rules_reach_the_writer():
    br = FakeBrain({"shots": []})
    sb.plan(br, _script(), dict(CH, id="cricket_ke_kisse"), log=lambda *a: None)
    assert "never be recognisable" in br.prompts[0]
    br = FakeBrain({"shots": []})
    sb.plan(br, _script(), dict(CH, id="itihaas_ke_raaz"), log=lambda *a: None)
    assert "Mughal" in br.prompts[0]


def test_quota_block_skips_source_until_tomorrow(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "QUOTA", tmp_path / "q.json")
    assert sb._open("cloudflare")
    sb._block("cloudflare")
    assert not sb._open("cloudflare")
    assert json.loads((tmp_path / "q.json").read_text())["cloudflare"] > time.time()


def test_scene_redraws_until_eyes_pass(tmp_path, monkeypatch):
    pics = []

    def fake_draw(prompt, seed, size, variant=0):
        p = tmp_path / f"p{variant}.jpg"
        Image.new("RGB", (64, 112)).save(p)
        pics.append(variant)
        return p, "cloudflare"
    verdicts = iter([{"score": 4, "text": True, "wrong": "", "ok": False},
                     {"score": 9, "text": False, "wrong": "", "ok": True}])
    monkeypatch.setattr(sb, "draw", fake_draw)
    monkeypatch.setattr(sb, "eyes", lambda *a, **k: next(verdicts))
    v = sb.scene({"_prompt": "x", "narration": "n", "see": "s"}, "", (1080, 1920), log=lambda *a: None)
    assert pics == [0, 1] and v["path"].name == "p1.jpg" and v["match"] == 0.9 and v["frame"] == "full"
    assert v["credit"] == "AI-generated image"                   # AI label path stays on


def test_scene_none_when_no_free_picture_left(monkeypatch):
    monkeypatch.setattr(sb, "draw", lambda *a, **k: None)
    assert sb.scene({"_prompt": "x"}, "", (1080, 1920)) is None


def test_eyes_without_key_never_blocks(tmp_path):
    p = tmp_path / "a.jpg"
    Image.new("RGB", (32, 32)).save(p)
    assert sb.eyes(p, "n", "s")["ok"]


def test_cloudflare_daily_limit_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "QUOTA", tmp_path / "q.json")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")

    class R:
        status_code = 429
        headers = {"content-type": "application/json"}

        def json(self):
            return {"errors": [{"code": 4006, "message": "daily free allocation"}], "success": False}
    sent = []
    monkeypatch.setattr(sb.requests, "post", lambda url, **k: sent.append(k["json"]) or R())
    assert sb._cloudflare("p", 1) is None and not sb._open("cloudflare")
    assert set(sent[0]) == {"prompt", "steps"}                   # FLUX schema has no seed (additionalProperties false)
    assert len(sent) == len(sb.CF_MODELS)                        # every backup model tried once, then the day is over
    assert sb._cloudflare("p", 1) is None and len(sent) == len(sb.CF_MODELS)   # no wasted calls after the block


def test_cloudflare_minute_limit_waits_not_blocks(monkeypatch, tmp_path):
    """17 Nov: a per-minute 429 blocked all pictures for a whole day; now it waits and the next try draws."""
    monkeypatch.setattr(sb, "QUOTA", tmp_path / "q.json")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setattr(sb.time, "sleep", lambda s: None)
    import base64
    replies = [(429, {"errors": [{"code": 3040, "message": "Capacity temporarily exceeded"}]}),
               (200, {"result": {"image": base64.b64encode(b"jpg").decode()}})]

    class R:
        def __init__(self, code, data):
            self.status_code, self._d = code, data
            self.headers = {"content-type": "application/json"}

        def json(self):
            return self._d
    monkeypatch.setattr(sb.requests, "post", lambda url, **k: R(*replies.pop(0)))
    assert sb._cloudflare("p", 1) == b"jpg" and sb._open("cloudflare") and sb._open("cf_flux")


def test_images_blocked_only_when_both_sources_are_out(monkeypatch, tmp_path):
    """Owner 15 Nov: when the free pictures run out the video waits; it is never made of word cards."""
    monkeypatch.setattr(sb, "QUOTA", tmp_path / "q.json")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("HF_TOKEN", "h")
    assert not sb.images_blocked()
    sb._block("cloudflare")
    assert not sb.images_blocked()                    # HF still draws
    sb._block("hf")
    assert sb.images_blocked() and sb.reset_at() > time.time()


def test_hf_client_gets_the_token_under_its_real_name(monkeypatch, tmp_path):
    """gradio_client 1.x takes hf_token=; token= raised TypeError so the HF fallback never ran."""
    import sys
    import types
    seen = {}

    class FakeClient:
        def __init__(self, space, **k):
            seen.update(k)

        def predict(self, **k):
            p = tmp_path / "x.webp"
            p.write_bytes(b"img")
            return (str(p), 1)
    monkeypatch.setattr(sb, "QUOTA", tmp_path / "q.json")
    monkeypatch.setenv("HF_TOKEN", "h")
    monkeypatch.setitem(sys.modules, "gradio_client", types.SimpleNamespace(Client=FakeClient))
    assert sb._hf("p", 1, (1080, 1920)) == b"img" and seen.get("hf_token") == "h"


def test_memory_bundle_never_carries_videos(tmp_path, monkeypatch):
    from engine.cloud import state
    from cryptography.fernet import Fernet
    monkeypatch.setenv("STATE_KEY", Fernet.generate_key().decode())
    (tmp_path / "data/telegram/previews").mkdir(parents=True)
    (tmp_path / "data/telegram/previews/x.mp4").write_bytes(b"0" * 1000)
    (tmp_path / "data/telegram/state.json").write_text("{}")
    out = tmp_path / "out"
    assert state.unpack(state.pack(tmp_path), out) == 1
    assert not (out / "data/telegram/previews/x.mp4").exists()


def test_pollinations_draws_and_blocks_when_pollen_is_gone(monkeypatch, tmp_path):
    """17 Nov: third free picture source (Z-Image Turbo, Apache 2.0) once Cloudflare's daily neurons are used."""
    monkeypatch.setattr(sb, "QUOTA", tmp_path / "q.json")
    monkeypatch.setenv("POLLINATIONS_KEY", "sk_test")
    replies = [(200, "image/jpeg", b"img"), (402, "application/json", b"{}")]
    seen = []

    class R:
        def __init__(self, code, ct, body):
            self.status_code, self.headers, self.content = code, {"content-type": ct}, body
            self.ok = code < 400
    monkeypatch.setattr(sb.requests, "get", lambda url, **k: seen.append(k["params"]) or R(*replies.pop(0)))
    assert sb._pollinations("p", 1, (1080, 1920)) == b"img"
    assert seen[0]["model"] == "zimage" and (seen[0]["width"], seen[0]["height"]) == (1080, 1920)
    assert sb._pollinations("p", 1, (1080, 1920)) is None and not sb._open("pollinations")
    sb._block("cloudflare")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert sb.images_blocked()
