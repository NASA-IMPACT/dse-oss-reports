"""Parallel GitHub queries for authored commits and resolved issues/PRs."""

from datetime import datetime

import pandas as pd

Task = tuple[str, str, str]  # (org, repo, username)
Contributor = tuple[str, str]  # (name, username)


def fetch_commits(
    token: str | None,
    tasks: list[Task],
    time_start: datetime,
    time_end: datetime,
    *,
    max_workers: int = 3,
) -> pd.DataFrame:
    """Fetch commits authored by each ``username`` to the default branch of each ``(org, repo)``.

    Only counts commits whose author timestamp falls within ``[time_start, time_end]``.
    Uses a thread pool of ``max_workers`` for parallel API calls; each thread gets its
    own ``Github`` client to dodge thread-safety issues. Returns a DataFrame with columns
    ``sha, message, author, committer, url, total_changes, organization, repository``.
    """
    raise NotImplementedError


def fetch_resolved(
    token: str | None,
    tasks: list[Task],
    contributors: list[Contributor],
    time_start: datetime,
    time_end: datetime,
    *,
    max_workers: int = 10,
) -> pd.DataFrame:
    """Fetch closed issues/PRs in which each contributor was involved.

    "Involved" uses GitHub's ``involves:`` qualifier (author, assignee, mentioned, or
    commenter). One search query per contributor covers all configured repos via repeated
    ``repo:`` filters; results are filtered down to the explicit (org, repo, contributor)
    triples in ``tasks`` before returning. Returns a DataFrame with columns
    ``number, title, type, state, author, url, created_at, updated_at, organization,
    repository, contributor``.
    """
    raise NotImplementedError
