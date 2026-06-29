"""Tests for Outcome / RunManifest and the run_outcome boundary."""

import json

import pytest

from dse_oss_reports.outcome import Outcome, RunManifest, collect_records, run_outcome
from dse_oss_reports.retry import RateLimitExhausted
from tests.utils import run


# --- Outcome / RunManifest -------------------------------------------------


def test_outcome_constructors():
    assert Outcome.ok("t", [{"a": 1}]).status == "ok"
    deg = Outcome.degraded("t", "404")
    assert deg.status == "degraded"
    assert deg.records == []


def test_manifest_degraded_fraction():
    m = RunManifest([Outcome.ok("a", []), Outcome.degraded("b", "x"), Outcome.failed("c", "y")])
    assert m.degraded_fraction() == pytest.approx(2 / 3)


def test_manifest_empty_fraction_is_zero():
    assert RunManifest([]).degraded_fraction() == 0.0


def test_collect_records_flattens_only_ok():
    outcomes = [Outcome.ok("a", [{"n": 1}, {"n": 2}]), Outcome.degraded("b", "x")]
    assert collect_records(outcomes) == [{"n": 1}, {"n": 2}]


def test_manifest_to_json_counts_and_redacts():
    m = RunManifest([Outcome.ok("a", [{"n": 1}]), Outcome.degraded("c", "boom ghp_SECRET123456")])
    data = json.loads(m.to_json())
    assert data["counts"] == {"ok": 1, "degraded": 1, "failed": 0}
    reasons = [o["reason"] for o in data["outcomes"] if o["reason"]]
    assert all("ghp_" not in r for r in reasons)


# --- run_outcome boundary --------------------------------------------------


def test_run_outcome_ok_wraps_records():
    async def work():
        return [{"n": 1}]

    out = run(run_outcome(work(), what="thing"))
    assert out.status == "ok"
    assert out.records == [{"n": 1}]


def test_run_outcome_non_throttle_error_is_degraded():
    async def work():
        raise RuntimeError("GitHub GET /x -> 404: Not Found")

    out = run(run_outcome(work(), what="thing"))
    assert out.status == "degraded"
    assert "404" in out.reason


def test_run_outcome_generic_error_is_degraded_and_redacted():
    async def work():
        raise ValueError("leaked ghp_abcDEF1234567890abcDEF12")

    out = run(run_outcome(work(), what="thing"))
    assert out.status == "degraded"
    assert "ghp_" not in out.reason


def test_run_outcome_throttle_exhaustion_reraises():
    async def work():
        raise RateLimitExhausted("GitHub POST /graphql rate limited; reset too far to wait")

    with pytest.raises(RateLimitExhausted):
        run(run_outcome(work(), what="thing"))


def test_run_outcome_plain_runtime_error_is_degraded_not_reraised():
    # A non-throttle RuntimeError whose text happens to contain "rate limited" must NOT
    # be misclassified as throttle exhaustion (the old substring check would have).
    async def work():
        raise RuntimeError("GraphQL errors: comment mentions a rate limited endpoint")

    out = run(run_outcome(work(), what="thing"))
    assert out.status == "degraded"
