from datetime import date

import pytest

from dse_oss_reports.pi_dates import get_current_pi, get_time_range


def test_returns_pi_whose_window_contains_today(sample_pi_dates):
    assert get_current_pi(sample_pi_dates, today=date(2025, 12, 25)) == "pi-26.1"


def test_returns_none_when_today_is_outside_all_windows(sample_pi_dates):
    assert get_current_pi(sample_pi_dates, today=date(2024, 1, 1)) is None
    assert get_current_pi(sample_pi_dates, today=date(2027, 1, 1)) is None


def test_window_boundaries_are_inclusive(sample_pi_dates):
    # pi-26.1 starts 20251019, ends 20260117
    assert get_current_pi(sample_pi_dates, today=date(2025, 10, 19)) == "pi-26.1"
    assert get_current_pi(sample_pi_dates, today=date(2026, 1, 17)) == "pi-26.1"
    # pi-26.2 starts the next day
    assert get_current_pi(sample_pi_dates, today=date(2026, 1, 18)) == "pi-26.2"


def test_get_time_range_returns_window_for_named_pi(sample_pi_dates):
    assert get_time_range(sample_pi_dates, pi="pi-26.1") == ("20251019", "20260117")


def test_get_time_range_falls_back_to_most_recent_when_today_is_after_all_windows(
    sample_pi_dates,
):
    # No `pi` given AND today is past every window → return the most recent PI's window
    assert get_time_range(sample_pi_dates, today=date(2027, 1, 1)) == ("20260118", "20260425")


def test_get_time_range_uses_current_pi_when_today_is_in_a_window(sample_pi_dates):
    assert get_time_range(sample_pi_dates, today=date(2025, 12, 25)) == ("20251019", "20260117")


def test_get_time_range_raises_on_unknown_pi(sample_pi_dates):
    with pytest.raises(KeyError):
        get_time_range(sample_pi_dates, pi="pi-99.9")
