"""Parallel GitHub queries for authored commits and resolved issues/PRs."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
from github import Auth, Github

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


def _make_client(token: str | None) -> Github:
    if token:
        return Github(auth=Auth.Token(token))
    return Github()


def _fetch_commits_for_task(
    g: Github,
    owner: str,
    repo: str,
    author: str,
    time_start: datetime,
    time_end: datetime,
) -> list[dict]:
    """Fetch commits for one (org, repo, author), with PR-dedup applied.

    A commit that belongs to exactly one PR is represented once per PR (the first
    commit encountered "wins"). A commit that belongs to no PR is kept as-is.
    Commits across multiple PRs are skipped (rare; mirrors the existing scripts).
    """
    try:
        repo_obj = g.get_repo(f"{owner}/{repo}")
        commits = repo_obj.get_commits(author=author, since=time_start, until=time_end)

        seen_prs: set[int] = set()
        kept = []
        for commit in commits:
            pulls = commit.get_pulls()
            count = pulls.totalCount
            if count == 0:
                kept.append(commit)
            elif count == 1:
                number = pulls[0].number
                if number not in seen_prs:
                    seen_prs.add(number)
                    kept.append(commit)
            # commits in >1 PRs: skip

        return [
            {
                "sha": c.sha,
                "message": c.commit.message.split("\n")[0],
                "author": c.commit.author.name,
                "committer": c.commit.committer.name,
                "url": c.html_url,
                "total_changes": c.stats.total if c.stats else 0,
                "organization": owner,
                "repository": repo,
            }
            for c in kept
        ]
    except Exception:
        logger.exception("Failed to fetch commits for %s/%s by %s", owner, repo, author)
        return []


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

    def process(task: Task) -> list[dict]:
        owner, repo, author = task
        g = _make_client(token)
        try:
            return _fetch_commits_for_task(g, owner, repo, author, time_start, time_end)
        finally:
            g.close()

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process, t) for t in tasks]
        for future in as_completed(futures):
            rows.extend(future.result())

    return pd.DataFrame(rows, columns=_COMMIT_COLUMNS)


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


def _fetch_resolved_for_contributor(
    g: Github,
    tasks: list[Task],
    contributor: str,
    time_start: datetime,
    time_end: datetime,
) -> list[dict]:
    """Fetch closed issues/PRs involving one contributor across all task repos."""
    try:
        start_str = time_start.strftime("%Y-%m-%d")
        end_str = time_end.strftime("%Y-%m-%d")
        repo_filters = " ".join(f"repo:{owner}/{repo}" for owner, repo, _ in tasks)
        base_query = f"{repo_filters} involves:{contributor} closed:{start_str}..{end_str}"

        issues = g.search_issues(f"is:issue {base_query}")
        # Exclude PRs the contributor authored — they're already counted as commits.
        prs = g.search_issues(f"is:pr {base_query} -author:{contributor}")

        task_set = set(tasks)
        rows = []
        for item in [*issues, *prs]:
            owner = item.repository.owner.login
            repo = item.repository.name
            if (owner, repo, contributor) not in task_set:
                continue
            is_pr = item.pull_request is not None
            rows.append(
                {
                    "number": item.number,
                    "title": item.title,
                    "type": "PR" if is_pr else "Issue",
                    "state": item.state,
                    "author": item.user.login if item.user else None,
                    "url": item.html_url,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    "organization": owner,
                    "repository": repo,
                    "contributor": contributor,
                }
            )
        return rows
    except Exception:
        logger.exception("Failed to fetch resolved issues/PRs for %s", contributor)
        return []


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

    def process(contributor_pair: Contributor) -> list[dict]:
        _name, username = contributor_pair
        g = _make_client(token)
        try:
            return _fetch_resolved_for_contributor(g, tasks, username, time_start, time_end)
        finally:
            g.close()

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process, c) for c in contributors]
        for future in as_completed(futures):
            rows.extend(future.result())

    return pd.DataFrame(rows, columns=_RESOLVED_COLUMNS)
