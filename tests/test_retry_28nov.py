"""28 Nov (P10): /retry offers posts that gave up for a platform reason (never gate holds, never older than 3 days)
and queues them again with fresh attempts."""
import time

from engine import telegram_bot as tb
from engine.core.ledger import Ledger


def _dead(led, key, err, age_s=60):
    led.enqueue("post", key, {})
    j = [x for x in led.jobs(kind="post") if x["key"] == key][0]
    led._tx(lambda c: c.execute("UPDATE jobs SET state='dead', last_error=?, updated=? WHERE id=?",
                                (err, time.time() - age_s, j["id"])))
    return j["id"]


def test_only_platform_failures_are_offered_and_retried(tmp_path):
    led = Ledger(tmp_path / "l.db")
    fb = _dead(led, "post:1126_0500_unsolved_after_dark_short:1:facebook", "Facebook refused the Reel: (#200) permission")
    _dead(led, "post:1124_0500_cosmos_unboxed_short:1:youtube", "🛑 blocked: quality: score 71/100")
    _dead(led, "post:1120_0500_x_short:1:instagram", "timeout", age_s=5 * 86400)
    jobs = tb.retryable(led)
    assert [j["id"] for j in jobs] == [fb] and jobs[0]["platform"] == "facebook"
    text, kb = tb.retry_menu(led)
    assert "26 Nov 05:00 Short on Facebook" in text and kb["inline_keyboard"][0][0]["callback_data"] == f"rt:{fb}"
    assert "1 post(s) queued again" in tb.retry_do(str(fb), led)
    assert [j for j in led.jobs(kind="post") if j["id"] == fb][0]["state"] == "queued"
    assert "no longer waiting" in tb.retry_do(str(fb), led)                     # a second tap does nothing
    assert tb.retry_menu(led)[1] is None


def test_retry_all(tmp_path):
    led = Ledger(tmp_path / "l.db")
    for p in ("facebook", "threads"):
        _dead(led, f"post:1127_0500_x_short:1:{p}", "HTTP 500")
    assert "Retry all 2" in str(tb.retry_menu(led)[1])
    assert "2 post(s) queued again" in tb.retry_do("all", led)
