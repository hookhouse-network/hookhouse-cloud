"""24 Nov: every Store asked the GitHub CLI for its token again; under load `gh auth token` took 8 s and once timed out
(20 s), and the PC helper stopped with "no GitHub token". The CLI's answer is kept for the process."""
import subprocess

import pytest

from engine.cloud import store


@pytest.fixture
def no_env(monkeypatch):
    for k in ("STORE_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "HOOKHOUSE_GH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(store, "_CLI_TOKEN", "")
    monkeypatch.setattr("engine.cloud.setup._gh", lambda: "gh")


def test_the_cli_is_asked_once_per_process(no_env, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(1) or
                        subprocess.CompletedProcess(a, 0, stdout="tok123\n", stderr=""))
    assert store.token() == "tok123" and store.token() == "tok123" and len(calls) == 1


def test_a_slow_cli_later_does_not_stop_the_helper(no_env, monkeypatch):
    answers = [subprocess.CompletedProcess([], 0, stdout="tok123\n", stderr="")]

    def run(*a, **k):
        if answers:
            return answers.pop(0)
        raise subprocess.TimeoutExpired("gh", 20)
    monkeypatch.setattr(subprocess, "run", run)
    assert store.token() == "tok123" and store.token() == "tok123"


def test_no_token_at_all_still_says_so(no_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="x"))
    with pytest.raises(store.StoreError):
        store.token()


def test_an_environment_token_wins(no_env, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "envtok")
    monkeypatch.setattr(store, "_CLI_TOKEN", "old")
    assert store.token() == "envtok"
