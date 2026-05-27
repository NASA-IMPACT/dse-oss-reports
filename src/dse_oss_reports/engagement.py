"""Foundational "engagement" contributions: reviews, comments, discussions, opened issues.

A complement to ``queries.py`` (directed work). For each tracked contributor in
each curated repo, over the PI window, counts the *distinct items* (issues, PRs,
discussions) they engaged with by reviewing, commenting, opening (issues), or
participating in a discussion. Each item is counted once per contributor (kinds
collapsed); a contributor's own authored PRs are excluded as directed work.
"""

import logging
from datetime import datetime

import pandas as pd
from github import Auth, Github

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


def _make_client(token: str | None) -> Github:
    if token:
        return Github(auth=Auth.Token(token))
    return Github()


def _graphql(g: Github, query: str, variables: dict) -> dict:
    """Run a GraphQL query via PyGithub's requester; return the ``data`` payload."""
    _headers, data = g.requester.graphql_query(query, variables)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


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


def _fetch_reviews_and_opened_for_contributor(
    g: Github,
    tasks: list[Task],
    contributor: str,
    iso_from: str,
    iso_to: str,
) -> list[dict]:
    """Fetch one contributor's PR reviews + opened issues, filtered to ``tasks`` repos.

    ``iso_from``/``iso_to`` are ISO-8601 ``DateTime`` strings (the GraphQL
    ``contributionsCollection`` window). Paginates both connections to exhaustion.
    """
    task_repos = {(org, repo) for org, repo, user in tasks if user == contributor}
    rows: list[dict] = []
    review_cursor = issue_cursor = None
    review_done = issue_done = False
    try:
        while True:
            data = _graphql(
                g,
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
                break
        return rows
    except Exception:
        logger.exception("Failed to fetch reviews/opened for %s", contributor)
        return []


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


def _fetch_comment_threads_for_contributor(
    g: Github,
    tasks: list[Task],
    contributor: str,
    time_start: datetime,
    time_end: datetime,
) -> list[dict]:
    """Fetch distinct issues/PRs ``contributor`` commented on, scoped to task repos.

    Uses the ``commenter:`` search qualifier (precise: only comment authorship,
    unlike the broader ``involves:``). ``updated:`` bounds the window — search has
    no per-comment date filter, so this is a proxy for "active in the window".
    """
    task_repos = {(org, repo) for org, repo, user in tasks if user == contributor}
    if not task_repos:
        return []
    start_str = time_start.strftime("%Y-%m-%d")
    end_str = time_end.strftime("%Y-%m-%d")
    repo_filters = " ".join(f"repo:{org}/{repo}" for org, repo in sorted(task_repos))
    query = f"{repo_filters} commenter:{contributor} updated:{start_str}..{end_str}"
    try:
        rows = []
        for item in g.search_issues(query):
            org = item.repository.owner.login
            repo = item.repository.name
            if (org, repo) not in task_repos:
                continue
            is_pr = item.pull_request is not None
            rows.append(
                {
                    "number": item.number,
                    "title": item.title,
                    "type": "PullRequest" if is_pr else "Issue",
                    "url": item.html_url,
                    "kind": "comment",
                    "author": item.user.login if item.user else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                    "organization": org,
                    "repository": repo,
                    "contributor": contributor,
                }
            )
        return rows
    except Exception:
        logger.exception("Failed to fetch comment threads for %s", contributor)
        return []


def _dedupe_engagement(rows: list[dict]) -> pd.DataFrame:
    """Collapse raw activity records into one row per distinct (contributor, item).

    - Drops records for PRs the contributor authored (directed work).
    - Groups by (organization, repository, number, contributor); the per-item
      ``engagement_kinds`` column is the sorted, comma-joined set of ``kind``s.
    - Sorts by (organization, repository, number, contributor) for stable output.
    """
    kept = [r for r in rows if not (r["type"] == "PullRequest" and r["author"] == r["contributor"])]
    if not kept:
        return pd.DataFrame(columns=_ENGAGEMENT_COLUMNS)

    raw = pd.DataFrame(kept, columns=_RAW_KEYS)
    raw["number"] = raw["number"].astype("Int64")
    group_keys = ["organization", "repository", "number", "contributor"]

    # Aggregate kinds separately, then join with the first-occurrence metadata.
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
