"""Shared Program Increment calendar and helpers for resolving the current PI.

All DSE teams share the same fiscal calendar, so ``PI_DATES`` is library-managed
rather than per-team — bumping the library ref propagates new PI windows to every
consumer. Teams can override individual entries via ``[pi_dates]`` in their
``team.toml`` if they need to, but the default is to inherit from here.
"""

from datetime import date

PIDates = dict[str, tuple[str, str]]

# Shared org-wide PI calendar. Add new entries when each new quarter starts.
PI_DATES: PIDates = {
    "pi-25.2": ("20250119", "20250418"),
    "pi-25.3": ("20250419", "20250718"),
    "pi-25.4": ("20250719", "20251018"),
    "pi-26.1": ("20251019", "20260117"),
    "pi-26.2": ("20260118", "20260425"),
    "pi-26.3": ("20260426", "20260711"),
    "pi-26.4": ("20260712", "20261017"),
    "pi-27.1": ("20261018", "20270123"),
}


def get_current_pi(pi_dates: PIDates, today: date | None = None) -> str | None:
    """Return the PI name whose date range contains ``today`` (defaults to now), or ``None``."""
    today_str = (today or date.today()).strftime("%Y%m%d")
    for pi_name, (start, end) in pi_dates.items():
        if start <= today_str <= end:
            return pi_name
    return None


def get_time_range(
    pi_dates: PIDates,
    pi: str | None = None,
    *,
    today: date | None = None,
) -> tuple[str, str]:
    """Return the ``(start, end)`` date strings for ``pi``, or for the current PI if ``None``.

    Falls back to the most recently defined PI window if no PI matches today.
    Raises ``KeyError`` if ``pi`` is given but missing from ``pi_dates``.
    """
    if pi is not None:
        return pi_dates[pi]
    current = get_current_pi(pi_dates, today=today)
    if current is not None:
        return pi_dates[current]
    return list(pi_dates.values())[-1]
