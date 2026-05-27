"""Tests for engagement fetching and dedupe.

Network is avoided: source fetchers are monkeypatched, and the GraphQL/search
clients are faked with the minimal attribute shape engagement.py touches.
"""

from dse_oss_reports.engagement import (
    _ENGAGEMENT_COLUMNS,
    _dedupe_engagement,
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
