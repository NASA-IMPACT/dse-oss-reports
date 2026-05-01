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
    raise NotImplementedError


def get_time_range(pi_dates: PIDates, pi: str | None = None) -> tuple[str, str]:
    """Return the ``(start, end)`` date strings for ``pi``, or for the current PI if ``None``.

    Falls back to the most recently defined PI window if no PI matches today.
    """
    raise NotImplementedError
