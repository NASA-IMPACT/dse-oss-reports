"""Tests for engagement fetching and dedupe.

Network is avoided: source fetchers are monkeypatched, and the GraphQL/search
clients are faked with the minimal attribute shape engagement.py touches.
"""

from dse_oss_reports.engagement import _ENGAGEMENT_COLUMNS, _dedupe_engagement


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
