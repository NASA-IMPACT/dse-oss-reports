"""Tests for engagement fetching and dedupe.

Network is avoided: source fetchers are monkeypatched, and the GraphQL/search
clients are faked with the minimal attribute shape engagement.py touches.
"""

from datetime import datetime
from types import SimpleNamespace

from dse_oss_reports.engagement import (
    _ENGAGEMENT_COLUMNS,
    _dedupe_engagement,
    _fetch_comment_threads_for_contributor,
    _fetch_reviews_and_opened_for_contributor,
)


def _raw(**kw) -> dict:
    """Build a raw engagement record with sensible defaults."""
    base = {
        "number": 1,
        "title": "t",
        "type": "PullRequest",
        "url": "https://github.com/o/r/pull/1",
        "kind": "review",
        "author": "someone-else",
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-02T00:00:00+00:00",
        "organization": "o",
        "repository": "r",
        "contributor": "alice",
    }
    base.update(kw)
    return base


def test_dedupe_collapses_kinds_within_contributor_item():
    rows = [
        _raw(kind="review"),
        _raw(kind="comment"),
    ]
    df = _dedupe_engagement(rows)
    assert list(df.columns) == _ENGAGEMENT_COLUMNS
    assert len(df) == 1
    assert df.iloc[0]["engagement_kinds"] == "comment,review"


def test_dedupe_keeps_per_contributor_rows():
    rows = [
        _raw(contributor="alice", kind="review"),
        _raw(contributor="bob", kind="comment"),
    ]
    df = _dedupe_engagement(rows)
    assert len(df) == 2


def test_dedupe_drops_self_authored_prs():
    rows = [
        _raw(type="PullRequest", author="alice", contributor="alice", kind="comment"),
    ]
    df = _dedupe_engagement(rows)
    assert df.empty
    assert list(df.columns) == _ENGAGEMENT_COLUMNS


def test_dedupe_keeps_self_authored_issue_comment():
    # Commenting on an issue is engagement even if you opened it; only self-authored
    # PRs are dropped (directed authorship).
    rows = [_raw(type="Issue", author="alice", contributor="alice", kind="comment")]
    df = _dedupe_engagement(rows)
    assert len(df) == 1


def test_dedupe_empty():
    df = _dedupe_engagement([])
    assert df.empty
    assert list(df.columns) == _ENGAGEMENT_COLUMNS


def test_dedupe_single_kind_has_no_comma():
    df = _dedupe_engagement([_raw(kind="review")])
    assert df.iloc[0]["engagement_kinds"] == "review"


class FakeRequester:
    """Mimics PyGithub's ``Github.requester`` for graphql_query."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.calls = []

    def graphql_query(self, query: str, variables: dict):
        self.calls.append((query, variables))
        # PyGithub returns (headers, data); data is {"data": {...}}.
        return ({}, {"data": self._payload})


class FakeGithubGraphQL:
    def __init__(self, payload: dict):
        self.requester = FakeRequester(payload)

    def close(self):
        pass


def _contrib_payload():
    return {
        "user": {
            "contributionsCollection": {
                "pullRequestReviewContributions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "pullRequest": {
                                "number": 7,
                                "title": "Fix bug",
                                "url": "https://github.com/o/r/pull/7",
                                "author": {"login": "carol"},
                                "createdAt": "2026-02-01T00:00:00Z",
                                "updatedAt": "2026-02-02T00:00:00Z",
                                "repository": {"owner": {"login": "o"}, "name": "r"},
                            }
                        },
                        {
                            "pullRequest": {
                                "number": 99,
                                "title": "Other repo",
                                "url": "https://github.com/x/y/pull/99",
                                "author": {"login": "carol"},
                                "createdAt": "2026-02-01T00:00:00Z",
                                "updatedAt": "2026-02-02T00:00:00Z",
                                "repository": {"owner": {"login": "x"}, "name": "y"},
                            }
                        },
                    ],
                },
                "issueContributions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "issue": {
                                "number": 12,
                                "title": "Report upstream bug",
                                "url": "https://github.com/o/r/issues/12",
                                "author": {"login": "alice"},
                                "createdAt": "2026-02-03T00:00:00Z",
                                "updatedAt": "2026-02-03T00:00:00Z",
                                "repository": {"owner": {"login": "o"}, "name": "r"},
                            }
                        }
                    ],
                },
            }
        }
    }


def test_reviews_and_opened_filters_to_tasks():
    g = FakeGithubGraphQL(_contrib_payload())
    tasks = [("o", "r", "alice")]
    rows = _fetch_reviews_and_opened_for_contributor(
        g, tasks, "alice", "2026-01-18T00:00:00Z", "2026-04-25T00:00:00Z"
    )
    # PR #7 (review, in o/r) and issue #12 (opened, in o/r) kept; PR #99 (x/y) dropped.
    by_kind = {(r["kind"], r["number"]) for r in rows}
    assert ("review", 7) in by_kind
    assert ("opened", 12) in by_kind
    assert all(r["organization"] == "o" and r["repository"] == "r" for r in rows)
    assert 99 not in {r["number"] for r in rows}
    # Review records carry the PR author (someone else), not the contributor.
    review_row = next(r for r in rows if r["kind"] == "review")
    assert review_row["author"] == "carol"
    assert review_row["type"] == "PullRequest"


def test_reviews_and_opened_paginates_without_duplicating():
    # Reviews span two pages; issues fit on one page. The issue must appear once.
    page1 = {
        "user": {
            "contributionsCollection": {
                "pullRequestReviewContributions": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "R1"},
                    "nodes": [
                        {
                            "pullRequest": {
                                "number": 1,
                                "title": "a",
                                "url": "https://github.com/o/r/pull/1",
                                "author": {"login": "carol"},
                                "createdAt": "2026-02-01T00:00:00Z",
                                "updatedAt": "2026-02-02T00:00:00Z",
                                "repository": {"owner": {"login": "o"}, "name": "r"},
                            }
                        }
                    ],
                },
                "issueContributions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "issue": {
                                "number": 12,
                                "title": "i",
                                "url": "https://github.com/o/r/issues/12",
                                "author": {"login": "alice"},
                                "createdAt": "2026-02-03T00:00:00Z",
                                "updatedAt": "2026-02-03T00:00:00Z",
                                "repository": {"owner": {"login": "o"}, "name": "r"},
                            }
                        }
                    ],
                },
            }
        }
    }
    page2 = {
        "user": {
            "contributionsCollection": {
                "pullRequestReviewContributions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "pullRequest": {
                                "number": 2,
                                "title": "b",
                                "url": "https://github.com/o/r/pull/2",
                                "author": {"login": "carol"},
                                "createdAt": "2026-02-01T00:00:00Z",
                                "updatedAt": "2026-02-02T00:00:00Z",
                                "repository": {"owner": {"login": "o"}, "name": "r"},
                            }
                        }
                    ],
                },
                "issueContributions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [],
                },
            }
        }
    }

    class MultiCallRequester:
        def __init__(self, pages):
            self._pages = pages
            self.calls = 0

        def graphql_query(self, query, variables):
            payload = self._pages[min(self.calls, len(self._pages) - 1)]
            self.calls += 1
            return ({}, {"data": payload})

    class MultiCallGithub:
        def __init__(self, pages):
            self.requester = MultiCallRequester(pages)

        def close(self):
            pass

    g = MultiCallGithub([page1, page2])
    rows = _fetch_reviews_and_opened_for_contributor(
        g, [("o", "r", "alice")], "alice", "2026-01-18T00:00:00Z", "2026-04-25T00:00:00Z"
    )
    review_numbers = sorted(r["number"] for r in rows if r["kind"] == "review")
    issue_numbers = [r["number"] for r in rows if r["kind"] == "opened"]
    assert review_numbers == [1, 2]
    assert issue_numbers == [12]  # not duplicated despite the extra review page


def _fake_issue(number, *, is_pr, owner, name, author, title="t"):
    return SimpleNamespace(
        number=number,
        title=title,
        user=SimpleNamespace(login=author),
        html_url=f"https://github.com/{owner}/{name}/issues/{number}",
        created_at=datetime(2026, 2, 1),
        updated_at=datetime(2026, 2, 2),
        pull_request=SimpleNamespace() if is_pr else None,
        repository=SimpleNamespace(owner=SimpleNamespace(login=owner), name=name),
    )


class FakeSearchGithub:
    def __init__(self, results):
        self._results = results
        self.queries = []

    def search_issues(self, query):
        self.queries.append(query)
        return list(self._results)

    def close(self):
        pass


def test_comment_threads_filters_to_tasks_and_shapes_rows():
    results = [
        _fake_issue(7, is_pr=True, owner="o", name="r", author="carol"),
        _fake_issue(50, is_pr=False, owner="x", name="y", author="dave"),  # not a task repo
    ]
    g = FakeSearchGithub(results)
    tasks = [("o", "r", "alice")]
    rows = _fetch_comment_threads_for_contributor(
        g, tasks, "alice", datetime(2026, 1, 18), datetime(2026, 4, 25)
    )
    assert {r["number"] for r in rows} == {7}
    row = rows[0]
    assert row["kind"] == "comment"
    assert row["type"] == "PullRequest"
    assert row["author"] == "carol"
    assert row["contributor"] == "alice"
    # The search query uses commenter: scoped to the repo and the window.
    assert "commenter:alice" in g.queries[0]
    assert "repo:o/r" in g.queries[0]
