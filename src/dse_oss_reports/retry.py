"""Transport-agnostic GitHub throttle policy (operates on status + headers).

GitHub signals throttling with HTTP 403/429 plus a body that mentions a rate or
abuse limit. Primary-limit exhaustion sends ``x-ratelimit-remaining: 0`` and an
``x-ratelimit-reset`` epoch (no ``Retry-After``); secondary limits send
``Retry-After``. These helpers turn those signals into a retry delay so the same
policy works over any client (httpx response, etc.).
"""

import time
from collections.abc import Callable

DEFAULT_MAX_RETRIES = 5
_BASE_DELAY_SECONDS = 2.0


class RateLimitExhausted(RuntimeError):
    """Raised when GitHub throttling survives all retries (or the reset is too far off).

    A dedicated type so the fail-loud boundary (:func:`~dse_oss_reports.outcome.run_outcome`)
    can re-raise throttle exhaustion by class instead of fragile message-substring matching.
    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` sites still catch it.
    """


_MAX_DELAY_SECONDS = 60.0
# Longest we'll wait for a primary-limit window to reset before failing loud —
# a far-off reset means the budget is spent, so error rather than block.
_MAX_RESET_WAIT_SECONDS = 300.0
_RATE_LIMIT_MARKERS = ("rate limit", "secondary", "abuse", "throttle")


def is_rate_limited(status: int, body_text: str) -> bool:
    """True if a 403/429 response body indicates a GitHub rate/abuse/throttle limit."""
    if status not in (403, 429):
        return False
    lowered = (body_text or "").lower()
    return any(m in lowered for m in _RATE_LIMIT_MARKERS)


def _ci(headers: dict, key: str):
    """Case-insensitive header lookup (``key`` must be lowercase)."""
    for k, v in headers.items():
        if str(k).lower() == key:
            return v
    return None


def retry_delay(
    headers: dict, attempt: int, *, now: Callable[[], float] = time.time
) -> float | None:
    """Seconds to wait before retry ``attempt`` (0-based), or ``None`` to stop retrying.

    Precedence: ``Retry-After`` (secondary limits, capped) → ``x-ratelimit-reset``
    when ``x-ratelimit-remaining`` is 0 (primary exhaustion; ``None`` if the reset
    is further off than ``_MAX_RESET_WAIT_SECONDS``) → capped exponential backoff.
    """
    retry_after = _ci(headers, "retry-after")
    if retry_after is not None:
        try:
            return min(float(retry_after), _MAX_DELAY_SECONDS)
        except (TypeError, ValueError):
            pass
    remaining = _ci(headers, "x-ratelimit-remaining")
    reset = _ci(headers, "x-ratelimit-reset")
    if remaining is not None and reset is not None:
        try:
            if int(remaining) <= 0:
                wait = float(reset) - now()
                if wait > _MAX_RESET_WAIT_SECONDS:
                    return None
                return max(wait, 0.0)
        except (TypeError, ValueError):
            pass
    return min(_BASE_DELAY_SECONDS * (2**attempt), _MAX_DELAY_SECONDS)
