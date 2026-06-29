"""Async GitHub queries for authored commits and resolved issues/PRs.

Commits come from one batched GraphQL ``history`` query per repo (additions/deletions
and associated PRs inline — no REST N+1). Resolved issues/PRs come from the REST
issue-search bridge, preserving the existing ``involves:``/``closed:`` semantics. The
sync ``fetch_commits_and_resolved`` wrapper builds the client, runs both concurrently in
one event loop, and returns the same ``(commits_df, resolved_df)`` as before.
"""

import asyncio
import logging
from datetime import datetime

import pandas as pd

from dse_oss_reports.github_client import AsyncGitHubClient, search_item_repo
from dse_oss_reports.outcome import Outcome, RunManifest, collect_records, run_outcome

logger = logging.getLogger(__name__)

Task = tuple[str, str, str]  # (org, repo, username)
Contributor = tuple[str, str]  # (name, username)

_COMMIT_COLUMNS = [
    "sha",
    "message",
    "author",
    "committer",
    "url",
    "total_changes",
    "organization",
    "repository",
]

_RESOLVED_COLUMNS = [
    "number",
    "title",
    "type",
    "state",
    "author",
    "url",
    "created_at",
    "updated_at",
    "organization",
    "repository",
    "contributor",
]

_COMMITS_QUERY = """
query($owner:String!, $name:String!, $since:GitTimestamp!, $until:GitTimestamp!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    defaultBranchRef { target { ... on Commit {
      history(since:$since, until:$until, first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          oid messageHeadline additions deletions url
          author { name user { login } }
          committer { name }
          associatedPullRequests(first:5){ totalCount nodes { number } }
        }
      }
    }}}
  }
}
"""


async def _commits_for_repo(
    client: AsyncGitHubClient,
    owner: str,
    repo: str,
    tracked: set[str],
    since: str,
    until: str,
) -> list[dict]:
    """Fetch default-branch commits in ``[since, until]`` authored by a ``tracked`` login.

    PR-dedup mirrors the historical behavior, scoped per ``(login, pr_number)``: a commit
    in exactly one PR is kept once per PR (first wins); commits in no PR are kept as-is;
    commits spanning >1 PR are skipped. ``total_changes`` == additions + deletions, the
    GraphQL equivalent of the old REST ``commit.stats.total``.
    """
    cursor = None
    seen: set[tuple[str, int]] = set()
    rows: list[dict] = []
    while True:
        data = await client.graphql(
            _COMMITS_QUERY,
            {"owner": owner, "name": repo, "since": since, "until": until, "cursor": cursor},
        )
        repository = data.get("repository") or {}
        target = (repository.get("defaultBranchRef") or {}).get("target") or {}
        history = target.get("history") or {}
        for node in history.get("nodes", []):
            login = ((node.get("author") or {}).get("user") or {}).get("login")
            if login not in tracked:
                continue
            prs = node["associatedPullRequests"]
            count = prs["totalCount"]
            if count == 1:
                key = (login, prs["nodes"][0]["number"])
                if key in seen:
                    continue
                seen.add(key)
            elif count > 1:
                continue
            rows.append(
                {
                    "sha": node["oid"],
                    "message": node["messageHeadline"],
                    "author": (node.get("author") or {}).get("name"),
                    "committer": (node.get("committer") or {}).get("name"),
                    "url": node["url"],
                    "total_changes": node.get("additions", 0) + node.get("deletions", 0),
                    "organization": owner,
                    "repository": repo,
                }
            )
        page = history.get("pageInfo", {})
        if not page.get("hasNextPage"):
            return rows
        cursor = page.get("endCursor")


async def fetch_commits(
    client: AsyncGitHubClient, tasks: list[Task], time_start: datetime, time_end: datetime
) -> list[Outcome]:
    """Fetch authored commits for every ``(org, repo)`` in ``tasks``, once per repo.

    Tasks are grouped by repo and the repo's commit history is fetched a single time,
    then filtered to the tracked logins for that repo — fewer queries than fetching per
    ``(repo, contributor)``. Returns one :class:`Outcome` per repo (records keyed by
    ``_COMMIT_COLUMNS``); throttle exhaustion propagates.
    """
    since = time_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = time_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    by_repo: dict[tuple[str, str], set[str]] = {}
    for owner, repo, user in tasks:
        by_repo.setdefault((owner, repo), set()).add(user)
    return await asyncio.gather(
        *[
            run_outcome(
                _commits_for_repo(client, owner, repo, tracked, since, until),
                what=f"commits for {owner}/{repo}",
            )
            for (owner, repo), tracked in by_repo.items()
        ]
    )


async def _resolved_for_contributor(
    client: AsyncGitHubClient,
    tasks: list[Task],
    contributor: str,
    time_start: datetime,
    time_end: datetime,
) -> list[dict]:
    """Fetch closed issues/PRs involving one contributor across their task repos (REST search)."""
    start_str = time_start.strftime("%Y-%m-%d")
    end_str = time_end.strftime("%Y-%m-%d")
    # Scope to this contributor's repos only — one repo: per distinct repo, deduped — so
    # the query stays under GitHub search's length limit (vs. one per task row).
    repos = sorted({(owner, repo) for owner, repo, user in tasks if user == contributor})
    repo_filters = " ".join(f"repo:{owner}/{repo}" for owner, repo in repos)
    base_query = f"{repo_filters} involves:{contributor} closed:{start_str}..{end_str}"

    issues = await client.search_issues(f"is:issue {base_query}")
    # Exclude PRs the contributor authored — they're already counted as commits.
    prs = await client.search_issues(f"is:pr {base_query} -author:{contributor}")

    task_set = set(tasks)
    rows = []
    for item in [*issues, *prs]:
        owner, repo = search_item_repo(item)
        if (owner, repo, contributor) not in task_set:
            continue
        is_pr = "pull_request" in item
        rows.append(
            {
                "number": item["number"],
                "title": item["title"],
                "type": "PR" if is_pr else "Issue",
                "state": item["state"],
                "author": (item.get("user") or {}).get("login"),
                "url": item["html_url"],
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "organization": owner,
                "repository": repo,
                "contributor": contributor,
            }
        )
    return rows


async def fetch_resolved(
    client: AsyncGitHubClient,
    tasks: list[Task],
    contributors: list[Contributor],
    time_start: datetime,
    time_end: datetime,
) -> list[Outcome]:
    """Fetch closed issues/PRs each contributor was involved in. One Outcome per contributor."""
    return await asyncio.gather(
        *[
            run_outcome(
                _resolved_for_contributor(client, tasks, username, time_start, time_end),
                what=f"resolved for {username}",
            )
            for _name, username in contributors
        ]
    )


def _dedup_and_sort_resolved(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse cross-contributor duplicates and sort for stable CSV output.

    A single issue/PR involving multiple tracked contributors appears once per
    contributor in the raw search results. Drop duplicates on ``(organization,
    repository, number)`` (first row wins) and sort by the same triple.
    """
    if df.empty:
        return df
    return (
        df.drop_duplicates(subset=["organization", "repository", "number"])
        .sort_values(by=["organization", "repository", "number"])
        .reset_index(drop=True)
    )


def fetch_commits_and_resolved(
    token: str | None,
    tasks: list[Task],
    contributors: list[Contributor],
    time_start: datetime,
    time_end: datetime,
    *,
    max_workers: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, RunManifest]:
    """Fetch commits and resolved issues/PRs concurrently in one event loop.

    Builds a single :class:`AsyncGitHubClient` (concurrency = ``max_workers``) and runs
    the commit and search work together, so the two interleave under one rate-limit
    budget. Returns ``(commits_df, resolved_df, manifest)`` — the resolved frame is
    de-duped/sorted, and the manifest records every per-unit outcome. Throttle
    exhaustion propagates out of :func:`asyncio.run` to fail the run loudly.
    """

    async def _collect() -> tuple[list[Outcome], list[Outcome]]:
        async with AsyncGitHubClient(token, concurrency=max_workers) as client:
            return await asyncio.gather(
                fetch_commits(client, tasks, time_start, time_end),
                fetch_resolved(client, tasks, contributors, time_start, time_end),
            )

    logger.info(
        "Fetching %d commit-repo groups + %d contributors (concurrency=%d)...",
        len({(o, r) for o, r, _ in tasks}),
        len(contributors),
        max_workers,
    )
    commit_outcomes, resolved_outcomes = asyncio.run(_collect())
    commits_df = pd.DataFrame(collect_records(commit_outcomes), columns=_COMMIT_COLUMNS)
    resolved_df = _dedup_and_sort_resolved(
        pd.DataFrame(collect_records(resolved_outcomes), columns=_RESOLVED_COLUMNS)
    )
    manifest = RunManifest([*commit_outcomes, *resolved_outcomes])
    logger.info(
        "Found %d commits and %d resolved issues/PRs (after dedup); %.0f%% units degraded",
        len(commits_df),
        len(resolved_df),
        manifest.degraded_fraction() * 100,
    )
    return commits_df, resolved_df, manifest
