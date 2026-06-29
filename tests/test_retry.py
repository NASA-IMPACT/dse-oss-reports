"""Tests for the transport-agnostic GitHub throttle policy (status + headers only)."""

from dse_oss_reports import retry

_NOW = 1_000_000.0


def _now():
    return _NOW


def test_is_rate_limited_markers():
    assert retry.is_rate_limited(429, "temporarily being throttled")
    assert retry.is_rate_limited(403, "You have exceeded a secondary rate limit")
    assert not retry.is_rate_limited(403, "Forbidden")
    assert not retry.is_rate_limited(404, "rate limit")  # wrong status


def test_retry_delay_retry_after_wins_and_caps():
    assert retry.retry_delay({"Retry-After": "7"}, 0, now=_now) == 7.0
    assert retry.retry_delay({"retry-after": "9999"}, 0, now=_now) == retry._MAX_DELAY_SECONDS


def test_retry_delay_exponential_without_headers():
    assert retry.retry_delay({}, 0, now=_now) == retry._BASE_DELAY_SECONDS
    assert retry.retry_delay({}, 2, now=_now) == retry._BASE_DELAY_SECONDS * 4


def test_retry_delay_waits_until_reset_on_primary_exhaustion():
    h = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(_NOW + 45))}
    assert retry.retry_delay(h, 0, now=_now) == 45.0


def test_retry_delay_clamps_past_reset_to_zero():
    h = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(_NOW - 10))}
    assert retry.retry_delay(h, 0, now=_now) == 0.0


def test_retry_delay_gives_up_when_reset_too_far():
    far = int(_NOW + retry._MAX_RESET_WAIT_SECONDS + 60)
    h = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(far)}
    assert retry.retry_delay(h, 0, now=_now) is None


def test_retry_delay_ignores_reset_when_requests_remain():
    h = {"x-ratelimit-remaining": "100", "x-ratelimit-reset": str(int(_NOW + 9999))}
    assert retry.retry_delay(h, 0, now=_now) == retry._BASE_DELAY_SECONDS
