"""Typed task outcomes + a run manifest, so incomplete data is visible, not silent.

Each fetch unit (one repo's commits, one contributor's resolved items, …) yields an
:class:`Outcome` via :func:`run_outcome`. A :class:`RunManifest` aggregates them so the
CLI can write a sidecar and fail the run when too much data is missing. Systemic
throttle exhaustion is *not* captured as an outcome — it re-raises to fail the whole
run loudly, because every later call would throttle too.
"""

import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Literal

from dse_oss_reports.redact import redact
from dse_oss_reports.retry import RateLimitExhausted

Status = Literal["ok", "degraded", "failed"]


@dataclass(frozen=True)
class Outcome:
    task: str
    status: Status
    records: list[dict] = field(default_factory=list)
    reason: str | None = None

    @classmethod
    def ok(cls, task: str, records: list[dict]) -> "Outcome":
        return cls(task, "ok", records, None)

    @classmethod
    def degraded(cls, task: str, reason: str) -> "Outcome":
        return cls(task, "degraded", [], reason)

    @classmethod
    def failed(cls, task: str, reason: str) -> "Outcome":
        return cls(task, "failed", [], reason)


async def run_outcome(coro: Awaitable[list], *, what: str) -> Outcome:
    """Await one fetch unit; classify the result.

    - success → ``Outcome.ok`` with the records.
    - throttle exhaustion (:class:`RateLimitExhausted`) → re-raise, so the whole run
      fails loud rather than shipping a gutted report.
    - any other error → ``Outcome.degraded`` (reason redacted) so one bad unit doesn't
      sink the run, but the gap is recorded.
    """
    try:
        records = await coro
        return Outcome.ok(what, records)
    except RateLimitExhausted:
        raise
    except Exception as exc:  # noqa: BLE001 - boundary collects all per-unit errors
        return Outcome.degraded(what, redact(f"{type(exc).__name__}: {exc}"))


def collect_records(outcomes: list[Outcome]) -> list[dict]:
    """Flatten the records of the successful outcomes."""
    return [r for o in outcomes if o.status == "ok" for r in o.records]


@dataclass
class RunManifest:
    outcomes: list[Outcome]

    def _counts(self) -> dict[str, int]:
        counts = {"ok": 0, "degraded": 0, "failed": 0}
        for o in self.outcomes:
            counts[o.status] += 1
        return counts

    def degraded_fraction(self) -> float:
        total = len(self.outcomes)
        if total == 0:
            return 0.0
        counts = self._counts()
        return (counts["degraded"] + counts["failed"]) / total

    def all_records(self) -> list[dict]:
        return collect_records(self.outcomes)

    def summary(self) -> dict:
        return {"counts": self._counts(), "degraded_fraction": self.degraded_fraction()}

    def to_json(self) -> str:
        return json.dumps(
            {
                **self.summary(),
                "outcomes": [
                    {
                        "task": redact(o.task),
                        "status": o.status,
                        "reason": redact(o.reason) if o.reason else None,
                        "record_count": len(o.records),
                    }
                    for o in self.outcomes
                ],
            },
            indent=2,
        )
