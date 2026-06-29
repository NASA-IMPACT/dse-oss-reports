"""Per-unit checkpoint store so a crashed fetch can resume instead of redoing everything.

Each completed ``ok`` :class:`~dse_oss_reports.outcome.Outcome` is persisted to a JSON
file keyed by a stable hash of ``(kind, identity, window, scope)``. On a resumed run,
units whose key is already on disk are reloaded instead of re-fetched; ``degraded`` /
``failed`` units are never persisted, so they always re-run. Records hold only public
GitHub data; the task label is redacted defensively. This is also why HTTP-level ETag
caching was dropped — GitHub's GraphQL API (most of our calls) has no conditional
requests, whereas this outcome cache is transport-agnostic and delivers the same
cheap-re-run benefit.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from dse_oss_reports.outcome import Outcome, run_outcome
from dse_oss_reports.redact import redact


class CheckpointStore:
    def __init__(self, run_dir: Path, *, enabled: bool = True) -> None:
        self.run_dir = Path(run_dir)
        self.enabled = enabled
        if self.enabled:
            self.run_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(*parts: object) -> str:
        """Stable hash of the unit's identity; differing scope/window → different key."""
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.run_dir / f"{key}.json"

    def has(self, key: str) -> bool:
        return self.enabled and self._path(key).exists()

    def load(self, key: str) -> Outcome | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return Outcome(data["task"], data["status"], data["records"], data.get("reason"))
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def save(self, key: str, outcome: Outcome) -> None:
        """Persist only successful outcomes; degraded/failed units re-run on resume."""
        if not self.enabled or outcome.status != "ok":
            return
        self._path(key).write_text(
            json.dumps(
                {
                    "task": redact(outcome.task),
                    "status": outcome.status,
                    "records": outcome.records,  # public GitHub data
                    "reason": None,
                }
            )
        )

    def clear(self) -> None:
        if not self.run_dir.exists():
            return
        for f in self.run_dir.glob("*.json"):
            f.unlink()


async def run_or_resume(
    store: CheckpointStore | None,
    key: str,
    coro_factory: Callable[[], Awaitable[list]],
    *,
    what: str,
) -> Outcome:
    """Reuse a checkpointed ``ok`` outcome if present, else run the unit and checkpoint it.

    ``coro_factory`` defers coroutine creation so a cache hit does no work. Throttle
    exhaustion propagates out of :func:`run_outcome` (nothing is saved), failing the run.
    """
    if store is not None and store.has(key):
        cached = store.load(key)
        if cached is not None:
            return cached
    outcome = await run_outcome(coro_factory(), what=what)
    if store is not None:
        store.save(key, outcome)
    return outcome
