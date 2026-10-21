"""Tests for the async commits + resolved fetchers and the sync DataFrame wrapper.

GitHub I/O is faked with ``httpx.MockTransport``; coroutines run via ``asyncio.run``
inside plain sync tests (no pytest-asyncio).
"""

import json
from datetime import datetime

import httpx
import pytest

from dse_oss_reports import queries
from dse_oss_reports.outcome import Outcome, collect_records
from dse_oss_reports.queries import fetch_commits, fetch_commits_and_resolved, fetch_resolved
from tests.utils import mock_client, run, search_handler, search_item

# ---------------------------------------------------------------------------
# Fixtures: GraphQL commit-history + REST search payloads
# ---------------------------------------------------------------------------


def _commit_node(oid, headline, prs, login="alice", adds=1, dels=0):
    return {
        "oid": oid,
        "messageHeadline": headline,
        "additions": adds,
        "deletions": dels,
        "url": f"https://github.com/acme/widget/commit/{oid}",
        "author": {"name": "Alice Example", "user": {"login": login}},
        "committer": {"name": "GitHub"},
        "associatedPullRequests": {"totalCount": len(prs), "nodes": [{"number": n} for n in prs]},
    }


def _history_payload(nodes):
    return {
        "data": {
            "repository": {
                "defaultBranchRef": {
                    "target": {
                        "history": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": nodes,
                        }
                    }
                }
            }
        }
    }


def _history_handler(by_repo_nodes):
    def handler(request):
        variables = json.loads(request.content)["variables"]
        nodes = by_repo_nodes.get((variables["owner"], variables["name"]), [])
        return httpx.Response(200, json=_history_payload(nodes))

    return handler


# ---------------------------------------------------------------------------
# fetch_commits (async, GraphQL)
# ---------------------------------------------------------------------------


def test_fetch_commits_dedups_filters_and_shapes_rows():
    nodes = [
        _commit_node("aaa", "feat a", [42]),
        _commit_node("bbb", "fix b", [42]),  # same PR -> dropped
        _commit_node("ccc", "chore c", []),  # standalone -> kept
        _commit_node("ddd", "merge", [1, 2]),  # >1 PR -> skipped
        _commit_node("eee", "other", [], login="mallory"),  # untracked -> dropped
    ]
    handler = _history_handler({("acme", "widget"): nodes})

    async def go():
        async with mock_client(handler) as c:
            return await fetch_commits(
                c, [("acme", "widget", "alice")], datetime(2026, 1, 1), datetime(2026, 4, 1)
            )

    rows = collect_records(run(go()))
    assert [r["sha"] for r in rows] == ["aaa", "ccc"]
    assert rows[0]["total_changes"] == 1
    assert rows[0]["organization"] == "acme"
    assert rows[0]["repository"] == "widget"


def test_fetch_commits_aggregates_across_repos():
    by_repo = {
        ("acme", "widget"): [_commit_node("aaa", "x", [], login="alice")],
        ("globex", "doohickey"): [_commit_node("bbb", "y", [], login="bob")],
    }
    handler = _history_handler(by_repo)

    async def go():
        async with mock_client(handler) as c:
            return await fetch_commits(
                c,
                [("acme", "widget", "alice"), ("globex", "doohickey", "bob")],
                datetime(2026, 1, 1),
                datetime(2026, 4, 1),
            )

    rows = collect_records(run(go()))
    assert sorted(r["sha"] for r in rows) == ["aaa", "bbb"]
    assert sorted(r["repository"] for r in rows) == ["doohickey", "widget"]


def test_fetch_commits_degrades_unit_on_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    async def go():
        async with mock_client(handler) as c:
            return await fetch_commits(
                c, [("acme", "widget", "alice")], datetime(2026, 1, 1), datetime(2026, 4, 1)
            )

    outcomes = run(go())
    assert [o.status for o in outcomes] == ["degraded"]
    assert collect_records(outcomes) == []


def test_fetch_commits_throttle_propagates_as_hard_failure():
    # A sustained 429 must NOT degrade to an empty outcome — it fails the whole run loud.
    def handler(request):
        return httpx.Response(429, json={"message": "secondary rate limit"})

    async def go():
        async with mock_client(handler, max_retries=1) as c:
            return await fetch_commits(
                c, [("acme", "widget", "alice")], datetime(2026, 1, 1), datetime(2026, 4, 1)
            )

    with pytest.raises(RuntimeError):
        run(go())


# ---------------------------------------------------------------------------
# fetch_resolved (async, REST search bridge)
# ---------------------------------------------------------------------------


def test_fetch_resolved_columns_type_and_task_filter():
    issues = [
        search_item(1, "acme", "widget", is_pr=False),
        search_item(2, "acme", "other", is_pr=False),  # repo not in tasks -> dropped
    ]
    prs = [search_item(7, "acme", "widget", is_pr=True)]
    handler = search_handler(issues, prs)

    async def go():
        async with mock_client(handler) as c:
            return await fetch_resolved(
                c,
                [("acme", "widget", "alice")],
                [("Alice Example", "alice")],
                datetime(2026, 1, 1),
                datetime(2026, 4, 1),
            )

    rows = collect_records(run(go()))
    assert {(r["number"], r["type"]) for r in rows} == {(1, "Issue"), (7, "PR")}
    assert all(r["organization"] == "acme" and r["repository"] == "widget" for r in rows)
    assert all(r["contributor"] == "alice" for r in rows)


def test_fetch_resolved_degrades_unit_on_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    async def go():
        async with mock_client(handler) as c:
            return await fetch_resolved(
                c,
                [("acme", "widget", "alice")],
                [("Alice Example", "alice")],
                datetime(2026, 1, 1),
                datetime(2026, 4, 1),
            )

    outcomes = run(go())
    assert [o.status for o in outcomes] == ["degraded"]
    assert collect_records(outcomes) == []


# ---------------------------------------------------------------------------
# fetch_commits_and_resolved (sync wrapper builds frames + dedups resolved)
# ---------------------------------------------------------------------------


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


def test_fetch_commits_and_resolved_builds_frames_and_dedups(monkeypatch):
    async def fake_commits(client, tasks, ts, te, **_kw):
        return [
            Outcome.ok(
                "commits",
                [
                    {
                        "sha": "abc",
                        "message": "m",
                        "author": "A",
                        "committer": "G",
                        "url": "u",
                        "total_changes": 3,
                        "organization": "acme",
                        "repository": "widget",
                    }
                ],
            )
        ]

    def _resolved_row(contributor):
        return {
            "number": 42,
            "title": "shared",
            "type": "Issue",
            "state": "closed",
            "author": "alice",
            "url": "u",
            "created_at": None,
            "updated_at": None,
            "organization": "acme",
            "repository": "widget",
            "contributor": contributor,
        }

    async def fake_resolved(client, tasks, contributors, ts, te, **_kw):
        # Same #42 from two contributors -> dedups to one row.
        return [
            Outcome.ok("alice", [_resolved_row("alice")]),
            Outcome.ok("bob", [_resolved_row("bob")]),
        ]

    monkeypatch.setattr(queries, "fetch_commits", fake_commits)
    monkeypatch.setattr(queries, "fetch_resolved", fake_resolved)
    monkeypatch.setattr(queries, "AsyncGitHubClient", lambda *a, **k: _DummyClient())

    commits_df, resolved_df, manifest = fetch_commits_and_resolved(
        None,
        [("acme", "widget", "alice")],
        [("A", "alice"), ("B", "bob")],
        datetime(2026, 1, 1),
        datetime(2026, 4, 1),
    )

    assert list(commits_df.columns) == queries._COMMIT_COLUMNS
    assert len(commits_df) == 1
    assert list(resolved_df.columns) == queries._RESOLVED_COLUMNS
    assert len(resolved_df) == 1  # cross-contributor duplicate collapsed
    assert resolved_df.iloc[0]["number"] == 42
    assert manifest.degraded_fraction() == 0.0
