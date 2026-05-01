"""Pure helpers for resolving the current Program Increment from a date table.

Each team maintains its own ``PI_DATES`` table (typically in their
``reports/constants.py``) — a dict mapping ``"pi-X.Y"`` to ``(start, end)``
date strings in ``YYYYMMDD`` format. The library takes the table as input
rather than owning the data, so different teams can use different windows.
"""

from datetime import date

PIDates = dict[str, tuple[str, str]]


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
