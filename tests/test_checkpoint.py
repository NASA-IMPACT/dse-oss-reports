"""Tests for the checkpoint store and the run_or_resume helper."""

import pytest

from dse_oss_reports.checkpoint import CheckpointStore, run_or_resume
from dse_oss_reports.outcome import Outcome
from dse_oss_reports.retry import RateLimitExhausted
from tests.utils import run


# --- CheckpointStore -------------------------------------------------------


def test_key_is_deterministic_and_scope_sensitive():
    k1 = CheckpointStore.key("commits", "acme/widget", "2026-01-01..2026-04-01")
    k2 = CheckpointStore.key("commits", "acme/widget", "2026-01-01..2026-04-01")
    k3 = CheckpointStore.key("commits", "acme/widget", "2026-04-01..2026-07-01")
    assert k1 == k2
    assert k1 != k3


def test_save_and_load_ok_outcome_roundtrips(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("commits", "acme/widget")
    store.save(key, Outcome.ok("commits for acme/widget", [{"sha": "abc"}]))
    assert store.has(key)
    loaded = store.load(key)
    assert loaded.status == "ok"
    assert loaded.records == [{"sha": "abc"}]


def test_degraded_outcome_is_not_persisted(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("commits", "acme/widget")
    store.save(key, Outcome.degraded("commits for acme/widget", "404"))
    assert not store.has(key)
    assert store.load(key) is None


def test_clear_removes_checkpoints(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("commits", "acme/widget")
    store.save(key, Outcome.ok("t", [{"n": 1}]))
    assert store.has(key)
    store.clear()
    assert not store.has(key)


def test_disabled_store_is_a_noop(tmp_path):
    store = CheckpointStore(tmp_path, enabled=False)
    key = CheckpointStore.key("x")
    store.save(key, Outcome.ok("t", [{"n": 1}]))
    assert not store.has(key)
    assert store.load(key) is None


def test_persisted_task_label_is_redacted(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("x")
    store.save(key, Outcome.ok("leaked ghp_abcDEF1234567890abcDEF12", [{"n": 1}]))
    raw = (tmp_path / f"{key}.json").read_text()
    assert "ghp_" not in raw


# --- run_or_resume ---------------------------------------------------------


def test_run_or_resume_runs_and_saves_on_miss(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("commits", "acme/widget")
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        return [{"sha": "abc"}]

    out = run(run_or_resume(store, key, work, what="commits for acme/widget"))
    assert out.status == "ok"
    assert calls["n"] == 1
    assert store.has(key)  # saved for next time


def test_run_or_resume_uses_cache_and_skips_work(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("commits", "acme/widget")
    store.save(key, Outcome.ok("commits for acme/widget", [{"sha": "cached"}]))
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        return [{"sha": "fresh"}]

    out = run(run_or_resume(store, key, work, what="commits for acme/widget"))
    assert out.records == [{"sha": "cached"}]
    assert calls["n"] == 0  # the factory was never invoked


def test_run_or_resume_without_store_just_runs(tmp_path):
    calls = {"n": 0}

    async def work():
        calls["n"] += 1
        return [{"sha": "abc"}]

    out = run(run_or_resume(None, "k", work, what="thing"))
    assert out.status == "ok"
    assert calls["n"] == 1


def test_run_or_resume_propagates_throttle_and_saves_nothing(tmp_path):
    store = CheckpointStore(tmp_path)
    key = CheckpointStore.key("commits", "acme/widget")

    async def work():
        raise RateLimitExhausted("GitHub POST /graphql rate limited; retries exhausted (429)")

    with pytest.raises(RateLimitExhausted):
        run(run_or_resume(store, key, work, what="commits for acme/widget"))
    assert not store.has(key)
