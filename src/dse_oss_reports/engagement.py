"""Foundational "engagement" contributions: reviews, comments, discussions, opened issues.

A complement to ``queries.py`` (directed work). For each tracked contributor in each
curated repo, over the PI window, counts the *distinct items* they engaged with by
reviewing, commenting, opening (issues), or participating in a discussion. Reviews/opened
and discussions come from GraphQL; comments from the REST issue-search bridge. The sync
``fetch_engagement`` wrapper runs all three across one async client and de-dupes.
"""

import asyncio
import logging
from datetime import datetime

import pandas as pd

from dse_oss_reports.github_client import AsyncGitHubClient, search_item_repo
from dse_oss_reports.outcome import RunManifest, collect_records, run_outcome

logger = logging.getLogger(__name__)

Task = tuple[str, str, str]  # (org, repo, username)
Contributor = tuple[str, str]  # (name, username)

_ENGAGEMENT_COLUMNS = [
    "number",
    "title",
    "type",
    "url",
    "engagement_kinds",
    "created_at",
    "updated_at",
    "organization",
    "repository",
    "contributor",
]

# Raw-record keys produced by the source fetchers before dedupe.
_RAW_KEYS = [
    "number",
    "title",
    "type",
    "url",
    "kind",
    "author",
    "created_at",
    "updated_at",
    "organization",
    "repository",
    "contributor",
]

_CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!,
      $reviewCursor: String, $issueCursor: String) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      pullRequestReviewContributions(first: 100, after: $reviewCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          pullRequest {
            number title url
            author { login }
            createdAt updatedAt
            repository { owner { login } name }
          }
        }
      }
      issueContributions(first: 100, after: $issueCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          issue {
            number title url
            author { login }
            createdAt updatedAt
            repository { owner { login } name }
          }
        }
      }
    }
  }
}
"""


def _node_row(node: dict, type_: str, kind: str, org: str, repo: str, contributor: str) -> dict:
    """Shape a GraphQL issue/PR node into a raw engagement record."""
    author = (node.get("author") or {}).get("login")
    return {
        "number": node["number"],
        "title": node["title"],
        "type": type_,
        "url": node["url"],
        "kind": kind,
        "author": author,
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "organization": org,
        "repository": repo,
        "contributor": contributor,
    }


async def _fetch_reviews_and_opened_for_contributor(
    client: AsyncGitHubClient,
    tasks: list[Task],
    contributor: str,
    iso_from: str,
    iso_to: str,
) -> list[dict]:
    """Fetch one contributor's PR reviews + opened issues, filtered to ``tasks`` repos."""
    task_repos = {(org, repo) for org, repo, user in tasks if user == contributor}
    rows: list[dict] = []
    review_cursor = issue_cursor = None
    review_done = issue_done = False
    while True:
        data = await client.graphql(
            _CONTRIB_QUERY,
            {
                "login": contributor,
                "from": iso_from,
                "to": iso_to,
                "reviewCursor": review_cursor,
                "issueCursor": issue_cursor,
            },
        )
        cc = (data.get("user") or {}).get("contributionsCollection") or {}
        reviews = cc.get("pullRequestReviewContributions") or {}
        issues = cc.get("issueContributions") or {}

        if not review_done:
            for node in reviews.get("nodes", []):
                pr = node["pullRequest"]
                org = pr["repository"]["owner"]["login"]
                repo = pr["repository"]["name"]
                if (org, repo) in task_repos:
                    rows.append(_node_row(pr, "PullRequest", "review", org, repo, contributor))
            r_page = reviews.get("pageInfo", {})
            if r_page.get("hasNextPage"):
                review_cursor = r_page.get("endCursor")
            else:
                review_done = True

        if not issue_done:
            for node in issues.get("nodes", []):
                issue = node["issue"]
                org = issue["repository"]["owner"]["login"]
                repo = issue["repository"]["name"]
                if (org, repo) in task_repos:
                    rows.append(_node_row(issue, "Issue", "opened", org, repo, contributor))
            i_page = issues.get("pageInfo", {})
            if i_page.get("hasNextPage"):
                issue_cursor = i_page.get("endCursor")
            else:
                issue_done = True

        if review_done and issue_done:
            return rows


async def _fetch_comment_threads_for_contributor(
    client: AsyncGitHubClient,
    tasks: list[Task],
    contributor: str,
    time_start: datetime,
    time_end: datetime,
) -> list[dict]:
    """Fetch distinct issues/PRs ``contributor`` commented on, scoped to task repos (via search)."""
    task_repos = {(org, repo) for org, repo, user in tasks if user == contributor}
    if not task_repos:
        return []
    start_str = time_start.strftime("%Y-%m-%d")
    end_str = time_end.strftime("%Y-%m-%d")
    repo_filters = " ".join(f"repo:{org}/{repo}" for org, repo in sorted(task_repos))
    base_query = f"{repo_filters} commenter:{contributor} updated:{start_str}..{end_str}"
    # GitHub's issue/PR search requires ``is:issue`` or ``is:pull-request``; run both and merge.
    issues = await client.search_issues(f"is:issue {base_query}")
    prs = await client.search_issues(f"is:pr {base_query}")
    rows = []
    for item in [*issues, *prs]:
        org, repo = search_item_repo(item)
        if (org, repo) not in task_repos:
            continue
        is_pr = "pull_request" in item
        rows.append(
            {
                "number": item["number"],
                "title": item["title"],
                "type": "PullRequest" if is_pr else "Issue",
                "url": item["html_url"],
                "kind": "comment",
                "author": (item.get("user") or {}).get("login"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "organization": org,
                "repository": repo,
                "contributor": contributor,
            }
        )
    return rows


_DISCUSSIONS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url createdAt updatedAt
        author { login }
        comments(first: 100) {
          pageInfo { hasNextPage endCursor }
          nodes { author { login } }
        }
      }
    }
  }
}
"""


async def _fetch_discussions_for_repo(
    client: AsyncGitHubClient,
    org: str,
    repo: str,
    contributors: set[str],
    iso_from: str,
    iso_to: str,
) -> list[dict]:
    """Fetch discussions in ``org/repo`` a tracked contributor authored or replied to.

    Emits one record per (discussion, tracked participant), bounded by the discussion's
    ``updatedAt``. Comment pagination beyond the first 100 is not followed (a pragmatic
    cap — we only need presence of a tracked author).
    """
    rows: list[dict] = []
    cursor = None
    while True:
        data = await client.graphql(
            _DISCUSSIONS_QUERY, {"owner": org, "name": repo, "cursor": cursor}
        )
        disc_conn = ((data.get("repository") or {}).get("discussions")) or {}
        for node in disc_conn.get("nodes", []):
            updated = node.get("updatedAt") or ""
            # Nodes are UPDATED_AT DESC: once one predates the window, so do all the rest.
            if updated < iso_from:
                return rows
            if updated > iso_to:
                continue
            participants = set()
            author = (node.get("author") or {}).get("login")
            if author:
                participants.add(author)
            for c in (node.get("comments") or {}).get("nodes", []):
                c_author = (c.get("author") or {}).get("login")
                if c_author:
                    participants.add(c_author)
            for who in participants & contributors:
                rows.append(
                    {
                        "number": node["number"],
                        "title": node["title"],
                        "type": "Discussion",
                        "url": node["url"],
                        "kind": "discussion",
                        "author": author,
                        "created_at": node.get("createdAt"),
                        "updated_at": node.get("updatedAt"),
                        "organization": org,
                        "repository": repo,
                        "contributor": who,
                    }
                )
        page = disc_conn.get("pageInfo", {})
        if not page.get("hasNextPage"):
            return rows
        cursor = page.get("endCursor")


def _dedupe_engagement(rows: list[dict]) -> pd.DataFrame:
    """Collapse raw activity records into one row per distinct (contributor, item).

    - Drops records for PRs the contributor authored (directed work).
    - Groups by (organization, repository, number, contributor); ``engagement_kinds`` is
      the sorted, comma-joined set of ``kind``s.
    - Sorts by (organization, repository, number, contributor) for stable output.
    """
    kept = [r for r in rows if not (r["type"] == "PullRequest" and r["author"] == r["contributor"])]
    if not kept:
        return pd.DataFrame(columns=_ENGAGEMENT_COLUMNS)

    raw = pd.DataFrame(kept, columns=_RAW_KEYS)
    raw["number"] = raw["number"].astype("Int64")
    group_keys = ["organization", "repository", "number", "contributor"]

    kinds_agg = (
        raw.groupby(group_keys, sort=False)["kind"]
        .agg(lambda s: ",".join(sorted(set(s))))
        .rename("engagement_kinds")
        .reset_index()
    )
    first_meta = raw.drop_duplicates(subset=group_keys)[
        group_keys + ["title", "type", "url", "created_at", "updated_at"]
    ]
    collapsed = kinds_agg.merge(first_meta, on=group_keys, how="left")
    return collapsed[_ENGAGEMENT_COLUMNS].sort_values(by=group_keys).reset_index(drop=True)


def fetch_engagement(
    token: str | None,
    tasks: list[Task],
    contributors: list[Contributor],
    time_start: datetime,
    time_end: datetime,
    *,
    max_workers: int = 10,
) -> tuple[pd.DataFrame, RunManifest]:
    """Fetch foundational engagement (reviews, comments, discussions, opened issues).

    Runs per-contributor reviews/opened (GraphQL) + comments (REST search) and per-repo
    discussions (GraphQL) across one async client, merges the raw records, and de-dupes to
    one row per distinct ``(contributor, item)``. Returns ``(df, manifest)`` with ``df``
    keyed by ``_ENGAGEMENT_COLUMNS``; throttle exhaustion propagates to fail the run.
    """
    iso_from = time_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    iso_to = time_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    tracked = {username for _name, username in contributors}
    repos = sorted({(org, repo) for org, repo, _user in tasks})

    async def _collect() -> list:
        async with AsyncGitHubClient(token, concurrency=max_workers) as client:
            jobs = []
            for _name, username in contributors:
                jobs.append(
                    run_outcome(
                        _fetch_reviews_and_opened_for_contributor(
                            client, tasks, username, iso_from, iso_to
                        ),
                        what=f"reviews/opened for {username}",
                    )
                )
                jobs.append(
                    run_outcome(
                        _fetch_comment_threads_for_contributor(
                            client, tasks, username, time_start, time_end
                        ),
                        what=f"comments for {username}",
                    )
                )
            for org, repo in repos:
                jobs.append(
                    run_outcome(
                        _fetch_discussions_for_repo(client, org, repo, tracked, iso_from, iso_to),
                        what=f"discussions for {org}/{repo}",
                    )
                )
            return await asyncio.gather(*jobs)

    logger.info(
        "Fetching engagement: %d contributors x2 + %d repos (concurrency=%d)...",
        len(contributors),
        len(repos),
        max_workers,
    )
    outcomes = asyncio.run(_collect())
    df = _dedupe_engagement(collect_records(outcomes))
    manifest = RunManifest(outcomes)
    logger.info(
        "Found %d distinct engagement items (after dedupe); %.0f%% units degraded",
        len(df),
        manifest.degraded_fraction() * 100,
    )
    return df, manifest
