import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

import pytest

# Real keys arrived in .env on 14 Nov 2026 (Telegram paired, YouTube, Gemini, Groq, Cloudflare, HF). Tests must never
# see them: no test may message the owner's phone or call a real account. Tests that need a key set a fake one.
_REAL = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_API_KEY",
         "GEMINI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN", "PEXELS_API_KEY",
         "PIXABAY_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CF_KV_NAMESPACE_ID", "STATE_KEY",
         "HOOKHOUSE_CLOUD", "HOOKHOUSE_RUNNER", "GITHUB_ACTIONS", "HOOKHOUSE_REPO", "TG_WEBHOOK_SECRET", "META_APP_ID", "META_APP_SECRET", "META_USER_TOKEN",
         "GOOGLE_TTS_API_KEY", "THREADS_APP_ID", "THREADS_APP_SECRET", "USE_CLAUDE_CLI")


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    for k in _REAL:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _no_real_publish_log(monkeypatch, tmp_path):
    """No test may write into the real upload log (a Threads test once logged fake 't9' posts there)."""
    import engine.publish as pub
    monkeypatch.setattr(pub, "LOG", tmp_path / "publish_log_test.jsonl")


@pytest.fixture(autouse=True)
def _no_real_clip_records(monkeypatch, tmp_path):
    """Tests never write the PC's real used-footage or Kick lists (20 Nov: a test's fake footage marked as used)."""
    import engine.cr_footage as crf
    import engine.weekly as wk
    monkeypatch.setattr(wk, "PC_CLIP_USED", tmp_path / "pc_clip_used_test.json")
    monkeypatch.setattr(crf, "KICK_STATE", tmp_path / "kick_state_test.json")


@pytest.fixture(autouse=True)
def _no_real_picture_quota(monkeypatch, tmp_path):
    """Tests never read or write today's real free-picture limits (a blocked day made the scheduler skip videos)."""
    import engine.storyboard as sbm
    monkeypatch.setattr(sbm, "QUOTA", tmp_path / "image_quota_test.json")
    monkeypatch.setattr(sbm, "QUOTA_PC", tmp_path / "image_quota_pc_test.json")
    monkeypatch.setenv("HF_TOKEN", "test")


@pytest.fixture(autouse=True)
def _no_real_learning_state(monkeypatch, tmp_path):
    """Tests never read the learned posting times, heal queue or reviews of the real system (18 Nov)."""
    import engine.daily_review as dr
    import engine.heal as heal
    import engine.timing as timing
    monkeypatch.setattr(timing, "STATE", tmp_path / "timing_test.json")
    monkeypatch.setattr(heal, "QUEUE", tmp_path / "heal_queue_test.json")
    monkeypatch.setattr(dr, "REVIEWS", tmp_path / "reviews_test")
    import engine.preflight as pf
    monkeypatch.setattr(pf, "STATE", tmp_path / "preflight_test.json")


@pytest.fixture(autouse=True)
def _no_real_music_downloads(monkeypatch, tmp_path, request):
    """Renders in tests use the synthesised bed; the music library is tested with a fake session (18 Nov)."""
    import engine.media.music_library as ml
    monkeypatch.setattr(ml, "CATALOG", tmp_path / "music_catalog_test.json")
    monkeypatch.setattr(ml, "LIB", tmp_path / "music_lib_test")
    if "real_music_library" not in request.keywords:
        monkeypatch.setattr(ml, "track", lambda *a, **k: None)


def pytest_configure(config):
    config.addinivalue_line("markers", "real_music_library: use the real music_library.track (fake session)")
    config.addinivalue_line("markers", "real_events: use the real events.anniversary_hints (fake session)")


@pytest.fixture(autouse=True)
def _no_wikipedia_anniversaries(monkeypatch, request):
    """The planner's 'on this day' anniversaries call Wikipedia; tests stay offline (18 Nov)."""
    import engine.events as ev
    if "real_events" not in request.keywords:
        monkeypatch.setattr(ev, "anniversary_hints", lambda *a, **k: {})


@pytest.fixture(autouse=True)
def _no_http_retries(monkeypatch):
    """engine.core.http retries server errors with waits; tests simulate those errors on purpose (one call each)."""
    from engine.core import http
    monkeypatch.setattr(http.HTTP, "waits", ())


@pytest.fixture(autouse=True)
def _no_real_ledger(monkeypatch, tmp_path):
    """No test writes events or jobs into the real ledger (data/ledger.db) or the real heal queue."""
    import engine.core.ledger as led
    import engine.heal as heal
    monkeypatch.setenv("LEDGER_DB", str(tmp_path / "ledger_test.db"))
    monkeypatch.setattr(led, "_DEFAULT", None)
    monkeypatch.setattr(heal, "QUEUE", tmp_path / "heal_queue_test.json")
    import engine.allocator as alloc                       # 20 Nov: no test plans with the real volume allocation
    monkeypatch.setattr(alloc, "FILE", tmp_path / "allocation_test.json")
    import engine.cloud.kv_budget as kvb                   # 20 Nov: no test reads Cloudflare analytics or real counts
    monkeypatch.setattr(kvb, "FILE", tmp_path / "kv_usage_test.json")
    monkeypatch.setattr(kvb, "fetch_real", lambda *a, **k: None)
    import engine.cloud.kv as kvmod
    monkeypatch.setattr(kvmod, "_hashes_file", lambda: tmp_path / "kv_hashes_test.json")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_gates: run the real content/clip gates (not opened for the test)")
    config.addinivalue_line("markers", "live_config: use the real config/gates.yaml auto_approve settings")


@pytest.fixture(autouse=True)
def _gates_open_unless_tested(request, monkeypatch):
    """Most tests post 1-byte fake videos through upload_item/ask to test other things; the content gate would
    (rightly) block every one. Tests marked real_gates, and the gate test modules, keep the real gates."""
    mod = request.module.__name__
    if mod.endswith("test_potential_gate"):
        return
    import engine.topic_proof as tp                       # never a real YouTube search from a test
    monkeypatch.setattr(tp, "measure", lambda *a, **k: None)
    monkeypatch.setattr(tp, "FILE", Path(str(request.getfixturevalue("tmp_path"))) / "topic_proof_test.json")
    if request.node.get_closest_marker("real_gates") or mod.endswith(("test_content_gate", "test_clip_gate",
                                                                     "test_auto_approve")):
        return
    import engine.content_gate as cg
    monkeypatch.setattr(cg, "base_problems", lambda it, *a, **k: [])
    monkeypatch.setattr(cg, "platform_problems", lambda it, platform, *a, **k: [])
    import engine.clip_gate as clg
    monkeypatch.setattr(clg, "file_problems", lambda *a, **k: [])
    import engine.auto_approve as aa
    monkeypatch.setattr(aa, "eligible", lambda it, *a, **k: (False, "off in tests"))
