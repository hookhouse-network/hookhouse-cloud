"""27 Nov (P4 sagas): a Reject / Change after YouTube scheduling deletes the remote copy; a failed delete used to be a
one-off 'delete it yourself' message. It is now a job: retried with backoff, then heal queue + one owner message."""
from engine import publish_queue as pq
from engine.core import ledger


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def _led(tmp_path):
    return ledger.Ledger(tmp_path / "led.db", clock=Clock(), rng=lambda: 0.5)


def test_a_failed_delete_is_retried_until_it_works(tmp_path):
    led = _led(tmp_path)
    assert pq.enqueue_undo("1126_0500_x_short", "brain_snack", "VID1", led=led)
    assert not pq.enqueue_undo("1126_0500_x_short", "brain_snack", "VID1", led=led)      # idempotent
    answers = [False, True]
    calls = []
    deleter = lambda ch, vid: calls.append(vid) or answers.pop(0)
    assert pq.drain_undo(lambda m: None, led=led, deleter=deleter, notify=lambda t: None) == \
        {"undone": 0, "retry": 1, "dead": 0}
    led.clock.t += 10 * 3600                                                              # past the backoff
    assert pq.drain_undo(lambda m: None, led=led, deleter=deleter, notify=lambda t: None)["undone"] == 1
    assert calls == ["VID1", "VID1"]


def test_the_last_failure_goes_to_heal_and_the_owner_once(tmp_path, monkeypatch):
    led = _led(tmp_path)
    pq.enqueue_undo("1126_0500_x_short", "brain_snack", "VID2", led=led)
    healed, told = [], []
    from engine import heal
    monkeypatch.setattr(heal, "report", lambda *a, **k: healed.append(a))
    for _ in range(pq.UNDO_MAX_ATTEMPTS):
        pq.drain_undo(lambda m: None, led=led, deleter=lambda ch, vid: False, notify=told.append)
        led.clock.t += 24 * 3600
    assert len(healed) == 1 and len(told) == 1 and "VID2" in told[0]
