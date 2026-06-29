"""Tests for the async engagement fetchers and the sync dedupe wrapper.

GitHub I/O is faked with ``httpx.MockTransport``; coroutines run via ``asyncio.run``.
"""

from datetime import datetime

import httpx

from dse_oss_reports import engagement as eng
from dse_oss_reports.engagement import (
    _ENGAGEMENT_COLUMNS,
    _fetch_comment_threads_for_contributor,
    _fetch_discussions_for_repo,
    _fetch_reviews_and_opened_for_contributor,
    fetch_engagement,
)
from tests.utils import mock_client, run, search_handler, search_item


# ---------------------------------------------------------------------------
# reviews + opened (GraphQL contributionsCollection)
# ---------------------------------------------------------------------------


def _pr_node(number, org, repo, author="carol"):
    return {
        "pullRequest": {
            "number": number,
            "title": f"pr{number}",
            "url": f"https://github.com/{org}/{repo}/pull/{number}",
            "author": {"login": author},
            "createdAt": "2026-02-01T00:00:00Z",
            "updatedAt": "2026-02-02T00:00:00Z",
            "repository": {"owner": {"login": org}, "name": repo},
        }
    }


def _issue_node(number, org, repo, author="alice"):
    return {
        "issue": {
            "number": number,
            "title": f"issue{number}",
            "url": f"https://github.com/{org}/{repo}/issues/{number}",
            "author": {"login": author},
            "createdAt": "2026-02-01T00:00:00Z",
            "updatedAt": "2026-02-02T00:00:00Z",
            "repository": {"owner": {"login": org}, "name": repo},
        }
    }


def _contrib_payload(review_nodes, issue_nodes):
    cc = {
        "pullRequestReviewContributions": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": review_nodes,
        },
        "issueContributions": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": issue_nodes,
        },
    }
    return {"data": {"user": {"contributionsCollection": cc}}}


def test_reviews_and_opened_filters_to_task_repos():
    payload = _contrib_payload(
        [_pr_node(7, "o", "r")],
        [_issue_node(3, "o", "r"), _issue_node(9, "x", "y")],  # x/y not in tasks -> dropped
    )

    def handler(request):
        return httpx.Response(200, json=payload)

    async def go():
        async with mock_client(handler) as c:
            return await _fetch_reviews_and_opened_for_contributor(
                c, [("o", "r", "alice")], "alice", "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z"
            )

    rows = run(go())
    assert {(r["number"], r["kind"]) for r in rows} == {(7, "review"), (3, "opened")}


# ---------------------------------------------------------------------------
# comments (REST search bridge)
# ---------------------------------------------------------------------------


def test_comment_threads_rest_search():
    handler = search_handler(
        [search_item(5, "o", "r", is_pr=False)], [search_item(8, "o", "r", is_pr=True)]
    )

    async def go():
        async with mock_client(handler) as c:
            return await _fetch_comment_threads_for_contributor(
                c, [("o", "r", "alice")], "alice", datetime(2026, 1, 1), datetime(2026, 4, 1)
            )

    rows = run(go())
    assert {(r["number"], r["type"]) for r in rows} == {(5, "Issue"), (8, "PullRequest")}
    assert all(r["kind"] == "comment" for r in rows)


# ---------------------------------------------------------------------------
# discussions (GraphQL)
# ---------------------------------------------------------------------------


def test_discussions_emit_one_row_per_tracked_participant():
    payload = {
        "data": {
            "repository": {
                "discussions": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "number": 3,
                            "title": "d3",
                            "url": "u3",
                            "createdAt": "2026-02-01T00:00:00Z",
                            "updatedAt": "2026-02-10T00:00:00Z",
                            "author": {"login": "alice"},
                            "comments": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [{"author": {"login": "bob"}}],
                            },
                        },
                        {
                            "number": 5,
                            "title": "d5",
                            "url": "u5",
                            "createdAt": "2026-02-01T00:00:00Z",
                            "updatedAt": "2026-02-10T00:00:00Z",
                            "author": {"login": "mallory"},
                            "comments": {"nodes": []},
                        },
                    ],
                }
            }
        }
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    async def go():
        async with mock_client(handler) as c:
            return await _fetch_discussions_for_repo(
                c, "o", "r", {"alice", "bob"}, "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z"
            )

    rows = run(go())
    by_contrib = {(r["number"], r["contributor"]) for r in rows}
    assert (3, "alice") in by_contrib
    assert (3, "bob") in by_contrib
    assert 5 not in {r["number"] for r in rows}
    assert all(r["type"] == "Discussion" and r["kind"] == "discussion" for r in rows)


# ---------------------------------------------------------------------------
# fetch_engagement (sync wrapper: merge + dedupe)
# ---------------------------------------------------------------------------


def _raw(number, kind, contributor, author, type_="PullRequest", org="o", repo="r"):
    return {
        "number": number,
        "title": f"t{number}",
        "type": type_,
        "url": f"https://github.com/{org}/{repo}/x/{number}",
        "kind": kind,
        "author": author,
        "created_at": None,
        "updated_at": None,
        "organization": org,
        "repository": repo,
        "contributor": contributor,
    }


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


def test_fetch_engagement_merges_and_dedupes(monkeypatch):
    # Same PR #7 surfaces as both a review and a comment by alice -> one row, kinds merged.
    async def fake_reviews(client, tasks, contributor, iso_from, iso_to):
        return [_raw(7, "review", "alice", "carol")]

    async def fake_comments(client, tasks, contributor, ts, te):
        return [_raw(7, "comment", "alice", "carol")]

    async def fake_discussions(client, org, repo, contributors, iso_from, iso_to):
        return [_raw(3, "discussion", "alice", "alice", type_="Discussion")]

    monkeypatch.setattr(eng, "_fetch_reviews_and_opened_for_contributor", fake_reviews)
    monkeypatch.setattr(eng, "_fetch_comment_threads_for_contributor", fake_comments)
    monkeypatch.setattr(eng, "_fetch_discussions_for_repo", fake_discussions)
    monkeypatch.setattr(eng, "AsyncGitHubClient", lambda *a, **k: _DummyClient())

    df, manifest = fetch_engagement(
        "tok",
        [("o", "r", "alice")],
        [("Alice", "alice")],
        datetime(2026, 1, 18),
        datetime(2026, 4, 25),
    )

    assert list(df.columns) == _ENGAGEMENT_COLUMNS
    pr_row = df[df["number"] == 7].iloc[0]
    assert pr_row["engagement_kinds"] == "comment,review"
    assert set(df["number"]) == {7, 3}
    assert manifest.degraded_fraction() == 0.0
