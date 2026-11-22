"""22 Nov: local SD1.5 pictures on the PC (owner 20 Nov: "SD1.5-family models only as a fallback, idle + plugged in,
low priority, capped, benchmarked first"). Cloudflare retired its unbilled backups on 20 Nov, so FLUX's ~170 free
pictures a day are all the cloud gives. The PC draws the rest with DreamShaper 8 LCM through stable-diffusion.cpp."""
import io
import subprocess

import pytest
from PIL import Image

from engine import storyboard as sb
from engine.media import local_sd, visuals


def _png() -> bytes:
    b = io.BytesIO()
    Image.effect_noise((512, 896), 60).convert("RGB").save(b, "PNG")      # noise: big enough to pass the size check
    return b.getvalue()


@pytest.fixture
def pc(monkeypatch, tmp_path):
    """A PC with the model and sd-cli in place, switched on, idle and plugged in."""
    exe, model = tmp_path / "sd-cli.exe", tmp_path / "model.safetensors"
    exe.write_bytes(b"x")
    model.write_bytes(b"x")
    monkeypatch.setattr(local_sd, "EXE", exe)
    monkeypatch.setattr(local_sd, "MODEL", model)
    monkeypatch.setattr(local_sd, "COUNT", tmp_path / "count.json")
    conf = {"enabled": True, "max_day": 3, "idle_min": 3, "threads": 4, "steps": 4, "timeout_s": 600}
    monkeypatch.setattr(local_sd, "cfg", lambda: dict(conf))
    monkeypatch.setattr(local_sd, "idle_s", lambda: 3600.0)
    monkeypatch.setattr(local_sd, "plugged_in", lambda: True)
    runs = []

    def run(args, **k):
        runs.append((args, k))
        out = args[args.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(_png())
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(local_sd.subprocess, "run", run)
    return conf, runs


def test_draws_one_picture_at_low_priority_and_counts_it(pc):
    conf, runs = pc
    data = local_sd.draw("a tent in the snow at night", 12345, (1080, 1920))
    assert data and Image.open(io.BytesIO(data)).size == (1080, 1890)   # enlarged: full-screen, not a 'card'
    args, k = runs[0]
    assert args[args.index("-W") + 1] == "512" and args[args.index("-H") + 1] == "896"
    assert args[args.index("--sampling-method") + 1] == "lcm" and args[args.index("--cfg-scale") + 1] == "1.0"
    assert args[args.index("-t") + 1] == "4" and k["timeout"] == 600
    if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
        assert k["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS
    assert local_sd.used_today() == 1


def test_the_daily_cap_stops_it(pc):
    conf, runs = pc
    for _ in range(3):
        assert local_sd.draw("p", 1)
    assert local_sd.draw("p", 1) is None and len(runs) == 3
    assert "3 local pictures" in local_sd.why_not()


@pytest.mark.parametrize("change, reason", [
    (lambda m, c: c.update(enabled=False), "switched off"),
    (lambda m, c: m.setenv("GITHUB_ACTIONS", "true"), "only on the PC"),
    (lambda m, c: m.setattr(local_sd, "plugged_in", lambda: False), "battery"),
    (lambda m, c: m.setattr(local_sd, "MODEL", local_sd.MODEL.with_name("missing.safetensors")), "missing"),
])
def test_rules_that_stop_every_picture(pc, monkeypatch, change, reason):
    conf, runs = pc
    monkeypatch.setattr(local_sd, "cfg", lambda: dict(conf))
    change(monkeypatch, conf)
    assert reason in local_sd.why_not() and not local_sd.available()
    assert local_sd.draw("p", 1) is None and runs == []


def test_a_video_starts_only_while_the_pc_is_idle_but_finishes_its_pictures(pc, monkeypatch):
    monkeypatch.setattr(local_sd, "idle_s", lambda: 30.0)                # the owner is typing
    assert not local_sd.available() and "in use" in local_sd.why_not(start=True)
    assert local_sd.draw("p", 1)                                         # a started video still gets its picture


def test_a_failed_drawing_returns_none_and_is_not_counted(pc, monkeypatch):
    monkeypatch.setattr(local_sd.subprocess, "run",
                        lambda args, **k: subprocess.CompletedProcess(args, 1, "", "error: out of memory"))
    assert local_sd.draw("p", 1) is None and local_sd.used_today() == 0

    def slow(args, **k):
        raise subprocess.TimeoutExpired(args, 600)
    monkeypatch.setattr(local_sd.subprocess, "run", slow)
    assert local_sd.draw("p", 1) is None


def test_off_by_default_without_settings(monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "settings", lambda: {})
    assert local_sd.cfg()["enabled"] is False


def test_images_are_not_blocked_while_the_pc_can_draw(pc, monkeypatch):
    for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "HF_TOKEN", "POLLINATIONS_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert not sb.images_blocked()
    monkeypatch.setattr(local_sd, "idle_s", lambda: 10.0)
    assert sb.images_blocked()                                           # no new story video while the owner works


def test_storyboard_draw_falls_back_to_the_pc(pc, monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "CACHE", tmp_path / "cache")
    for name in ("_cloudflare", "_pollinations", "_hf"):
        monkeypatch.setattr(sb, name, lambda *a, **k: None)
    path, src = sb.draw("a quiet harbour at dawn", 7, (1080, 1920))
    assert src == "local_sd" and path.exists()
    assert sb.draw("a quiet harbour at dawn", 7, (1080, 1920))[1] == "cache"


def test_visuals_ai_image_uses_the_pc_when_cloudflare_is_used_up(pc, monkeypatch, tmp_path):
    conf, runs = pc
    monkeypatch.setattr(visuals, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setattr(sb, "_open", lambda source: False)              # FLUX's free allowance is used up
    v = visuals.ai_image("a lighthouse in a storm", "moody")
    assert v and v.source == local_sd.SOURCE and v.source.startswith("ai_") and v.credit == "AI-generated image"
    assert visuals.ai_image("a lighthouse in a storm", "moody").path == v.path and len(runs) == 1   # cached
    assert visuals.ai_image("a lighthouse at noon", "moody", local=False) is None and len(runs) == 1  # thumbnails


def test_the_real_settings_switch_it_on_with_a_key_yaml_keeps():
    """22 Nov: the first try said `on: true`, and YAML reads the key `on` as the boolean True: never switched on."""
    import yaml
    from engine.config import ROOT
    lp = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))["local_pictures"]
    assert lp.get("enabled") is True and True not in lp and lp["max_day"] > 0


def test_a_scene_redraws_a_local_picture_only_once(monkeypatch, tmp_path):
    """Each local picture costs ~2 CPU minutes: a scene keeps the better of two (cloud pictures still get three)."""
    from PIL import Image as _I
    calls = []

    def fake_draw(prompt, seed, size, variant=0, src="local_sd"):
        p = tmp_path / f"p{len(calls)}.jpg"
        _I.new("RGB", (8, 8)).save(p)
        calls.append(p)
        return p, src
    scores = iter([4, 6, 9])
    monkeypatch.setattr(sb, "draw", fake_draw)
    monkeypatch.setattr(sb, "eyes", lambda *a, **k: {"score": next(scores), "text": False, "wrong": "", "ok": False})
    v = sb.scene({"_prompt": "x", "narration": "n", "see": "s"}, "", (1080, 1920), log=lambda *a: None)
    assert len(calls) == sb.LOCAL_TRIES == 2 and v["path"] == calls[1] and v["source"] == "ai_scene_local_sd"
    calls.clear()
    scores = iter([4, 6, 5])
    monkeypatch.setattr(sb, "eyes", lambda *a, **k: {"score": next(scores), "text": False, "wrong": "", "ok": False})
    monkeypatch.setattr(sb, "draw", lambda p, s, z, variant=0: fake_draw(p, s, z, variant, src="cloudflare"))
    sb.scene({"_prompt": "x", "narration": "n", "see": "s"}, "", (1080, 1920), log=lambda *a: None)
    assert len(calls) == 3


def test_thumbnails_never_draw_on_the_pc(monkeypatch, tmp_path):
    """22 Nov: the first local video drew its 13th picture for the thumbnail (2 CPU minutes for a soft 512 px subject)."""
    from engine import story
    asked = []
    monkeypatch.setattr(story.visuals, "ai_image", lambda prompt, style="", local=True: asked.append(local) or None)
    monkeypatch.setattr(story, "rank_heroes", lambda script: [])
    try:
        story.make_thumbnails({"style": {"mood": "awe", "renderer": "v2"}}, {"thumbnail": {"subject_prompt": "x"}},
                              tmp_path)
    except Exception:  # noqa: BLE001 - only the picture request matters here, not the thumbnail renderer
        pass
    assert asked == [False]


def test_a_beat_draws_its_pc_picture_only_in_the_scene_drawer():
    """22 Nov (Cosmos beat 9): the beat's AI-image source drew a local picture, the eyes check turned it down, then
    the scene drawer drew two more. The source loop now asks the cloud models only; the scene drawer draws locally."""
    import inspect
    from engine import story
    src = inspect.getsource(story)
    i = src.index("def try_ai():")
    assert "local=False" in src[i:i + 600]


def test_pc_pictures_are_big_enough_for_the_full_screen_frame(tmp_path):
    """22 Nov: 512 px pictures were shown as small dark 'document' cards (story._v3_frame: short side under 650)."""
    from engine import story
    p = tmp_path / "pic.png"
    p.write_bytes(local_sd._enlarge(_png()))
    assert Image.open(p).size == (1080, 1890)
    assert story._v3_frame({"path": str(p), "source": local_sd.SOURCE, "credit": "AI-generated image"}) == "parallax"


def test_a_small_cached_pc_picture_is_enlarged_when_reused(monkeypatch, tmp_path):
    """PC pictures drawn before the enlargement (512 px) sit in the scene cache: a remake reuses them full-screen."""
    import hashlib
    monkeypatch.setattr(sb, "CACHE", tmp_path)
    prompt, seed, size = "a palace gate at night", 3, (1080, 1920)
    key = hashlib.md5(f"{prompt}|{seed}|{size}".encode()).hexdigest()
    Image.effect_noise((512, 896), 60).convert("RGB").save(tmp_path / f"{key}.jpg", quality=93)
    path, src = sb.draw(prompt, seed, size)
    assert src == "cache" and Image.open(path).size == (1080, 1890)
    Image.new("RGB", (1024, 1024)).save(path)                        # a cloud picture is left as it is
    sb.enlarge_small(path)
    assert Image.open(path).size == (1024, 1024)
